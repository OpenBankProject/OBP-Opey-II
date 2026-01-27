from fastapi import APIRouter, Request, Response, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from auth.session import session_cookie, backend, SessionData
from typing import Annotated, Any
from schema import UserInput, ChatMessage, StreamInput, ToolCallApproval
from ..opey_session import OpeySession
from langgraph.graph.state import CompiledStateGraph
from ..dependencies import get_stream_manager, get_opey_session
from ..streaming import StreamManager

import logging
import uuid
import os

logger = logging.getLogger('opey.service.routers.chat')

router = APIRouter(
    tags=["chat"],
    dependencies=[Depends(session_cookie)]
)

def _sse_response_example() -> dict[int, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@router.post("/invoke")
async def invoke(user_input: UserInput, request: Request, opey_session: Annotated[OpeySession, Depends(get_opey_session)]) -> ChatMessage:
    """
    Invoke the agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    """


    logger.info(f"Hello from invoke\n")


    # Update request count for usage tracking
    opey_session.update_request_count()

    agent: CompiledStateGraph = opey_session.graph
    kwargs, run_id = _parse_input(user_input, str(opey_session.session_id))
    try:
        response = await agent.ainvoke(**kwargs)
        output = ChatMessage.from_langchain(response["messages"][-1])
        logger.info(f"Replied to thread_id {kwargs['config']['configurable']['thread_id']} with message:\n\n {output.content}\n")

        # Update token usage if available
        if hasattr(response, 'total_tokens') and response.get('total_tokens'):
            opey_session.update_token_usage(response['total_tokens'])

        output.run_id = str(run_id)
        return output
    except Exception as e:
        logging.error(f"Error invoking agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream_agent(
    user_input: StreamInput, 
    request: Request, 
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> StreamingResponse:
    """Stream the agent's response to a user input"""
    # Log successful authentication
    logger.error(f"STREAM_ENDPOINT_DEBUG: Successfully authenticated, session_id: {stream_manager.opey_session.session_id}")
    logger.error(f"STREAM_ENDPOINT_DEBUG: User input: {user_input}")

    # Update request count for usage tracking
    stream_manager.opey_session.update_request_count()

    # Get the actual thread_id that will be used
    thread_id = user_input.thread_id or str(stream_manager.opey_session.session_id)
    
    # Build config with model context merged in
    config = stream_manager.opey_session.build_config({
        'configurable': {
            'thread_id': thread_id,
        }
    })

    async def stream_generator():
        from utils.cancellation_manager import cancellation_manager
        
        # Clear any stale cancellation flags from previous requests
        # This ensures a fresh start for each new stream request
        await cancellation_manager.clear_cancellation(thread_id)
        
        try:
            async for stream_event in stream_manager.stream_response(user_input, config):
                # Check if client disconnected
                if await request.is_disconnected():
                    logger.info(f"Client disconnected for thread {thread_id}")
                    await cancellation_manager.request_cancellation(thread_id)
                    break
                
                # Check if cancellation was requested via API
                if await cancellation_manager.is_cancelled(thread_id):
                    logger.info(f"Cancellation requested for thread {thread_id}, stopping stream")
                    break
                
                yield stream_manager.to_sse_format(stream_event)
        except GeneratorExit:
            # Handle generator being closed gracefully
            logger.info(f"Stream generator closed for thread {thread_id}")
            raise  # Re-raise to properly close the generator
        finally:
            # Clear cancellation flag after handling
            await cancellation_manager.clear_cancellation(thread_id)

    # Add thread_id to response headers for frontend synchronization
    headers = {"X-Thread-ID": thread_id}

    return StreamingResponse(stream_generator(), media_type="text/event-stream", headers=headers)

@router.post("/stream/{thread_id}/stop", dependencies=[Depends(session_cookie)])
async def stop_stream(thread_id: str) -> dict:
    """
    Request cancellation of an active stream.
    
    This signals to the streaming endpoint that the user wants to stop
    receiving tokens. The graph execution will cooperatively cancel when
    nodes check the cancellation flag.
    
    Note: This is cooperative cancellation - the actual stop may not be
    immediate as it depends on when the next cancellation check occurs.
    """
    from utils.cancellation_manager import cancellation_manager
    
    logger.info(f"Stop requested for thread: {thread_id}")
    await cancellation_manager.request_cancellation(thread_id)
    
    return {
        "status": "cancellation_requested",
        "thread_id": thread_id,
        "message": "Stream cancellation requested. The stream will stop at the next checkpoint."
    }


@router.post("/stream/{thread_id}/regenerate", response_class=StreamingResponse, responses=_sse_response_example(), dependencies=[Depends(session_cookie)])
async def regenerate_from_message(
    thread_id: str,
    request: Request,
    message_id: str,
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> StreamingResponse:
    """
    Regenerate the response starting from a specific message ID.
    
    This endpoint:
    1. Gets the current state for the thread
    2. Finds the target message by ID
    3. Removes all messages after that message using RemoveMessage
    4. Streams a new response from that point
    
    This is superior to checkpoint-based regeneration because:
    - Works correctly even when there are tool calls/messages between user messages
    - Allows regeneration from any specific message, not just the last user message
    - More explicit and predictable behavior
    
    Args:
        thread_id: The conversation thread
        message_id: The ID of the message to regenerate from (everything after this is removed)
        request: FastAPI request object
        stream_manager: Injected stream manager dependency
    
    Returns:
        StreamingResponse with SSE events
    """
    logger.info(f"Regenerate requested for thread: {thread_id}, from message: {message_id}")
    
    # Get the graph from the session
    agent = stream_manager.opey_session.graph
    
    # Build config for the thread
    config = stream_manager.opey_session.build_config({
        'configurable': {
            'thread_id': thread_id,
        }
    })
    
    try:
        # Get current state
        current_state = await agent.aget_state(config)
        
        if not current_state or not current_state.values:
            raise HTTPException(
                status_code=404,
                detail="No conversation history found for this thread"
            )
        
        # Get messages from state
        messages = current_state.values.get('messages', [])
        
        if not messages:
            
            raise HTTPException(
                status_code=400,
                detail="No messages found in conversation"
            )
        
        # Find the index of the target message
        target_index = None
        for i, msg in enumerate(messages):
            if getattr(msg, 'id', None) == message_id:
                target_index = i
                break
        
        if target_index is None:
            
            logger.error(f"Message ID {message_id} not found in messages: {[getattr(m, 'id', None) for m in messages]}")
            for msg in messages:
                logger.info(f"Message details: {msg.pretty_print()}")
            
            raise HTTPException(
                status_code=404,
                detail=f"Message with ID {message_id} not found in conversation"
            )
        
        # Determine which messages to remove (everything after the target message)
        messages_to_remove = messages[target_index + 1:]
        
        if not messages_to_remove:
            raise HTTPException(
                status_code=400,
                detail="No messages to regenerate - target message is already the last message"
            )
        
        logger.info(f"Removing {len(messages_to_remove)} messages after message {message_id}")
        
        # Use RemoveMessage to delete the messages
        # This works with the add_messages reducer in MessagesState
        from langchain_core.messages import RemoveMessage
        
        # Update state to remove messages after the target
        await agent.aupdate_state(
            config,
            {"messages": [RemoveMessage(id=msg.id) for msg in messages_to_remove]}
        )
        
        # Create a StreamInput with no message (we're continuing from the updated state)
        regenerate_input = StreamInput(
            message="",  # Empty - the state already has the context
            thread_id=thread_id,
        )
        
        # Update request count for usage tracking
        stream_manager.opey_session.update_request_count()
        
        async def stream_generator():
            from utils.cancellation_manager import cancellation_manager
            
            # Clear any stale cancellation flags
            await cancellation_manager.clear_cancellation(thread_id)
            
            try:
                # Stream from the updated state (with messages removed)
                async for stream_event in stream_manager.stream_response(
                    regenerate_input,
                    config  # Use the same config - state has been updated
                ):
                    # Check if client disconnected
                    if await request.is_disconnected():
                        logger.info(f"Client disconnected for thread {thread_id} during regeneration")
                        await cancellation_manager.request_cancellation(thread_id)
                        break
                    
                    # Check if cancellation was requested via API
                    if await cancellation_manager.is_cancelled(thread_id):
                        logger.info(f"Cancellation requested for thread {thread_id} during regeneration")
                        break
                    
                    yield stream_manager.to_sse_format(stream_event)
            except GeneratorExit:
                logger.info(f"Regenerate stream generator closed for thread {thread_id}")
                raise
            finally:
                await cancellation_manager.clear_cancellation(thread_id)
        
        headers = {
            "X-Thread-ID": thread_id,
            "X-Regenerated": "true",
            "X-Regenerated-From": message_id
        }
        return StreamingResponse(stream_generator(), media_type="text/event-stream", headers=headers)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during regenerate for thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate response: {str(e)}"
        )
        
        
@router.post("/approval/{thread_id}", response_class=StreamingResponse, responses=_sse_response_example(), dependencies=[Depends(session_cookie)])
async def user_approval(
    user_approval_response: ToolCallApproval,
    thread_id: str,
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> StreamingResponse:
    logger.info(f"[DEBUG] Approval endpoint user_response: {user_approval_response}\n")

    # Create stream input for approval continuation
    approval_user_input = StreamInput(
        message="",
        thread_id=thread_id,
        tool_call_approval=user_approval_response,
    )

    # Build config with model context merged in (approval_manager already included)
    config = stream_manager.opey_session.build_config({
        'configurable': {
            'thread_id': thread_id,
        }
    })

    async def stream_generator():
        async for stream_event in stream_manager.stream_response(
            stream_input=approval_user_input,
            config=config,
        ):
            yield stream_manager.to_sse_format(stream_event)

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.get("/threads/{thread_id}/messages", dependencies=[Depends(session_cookie)])
async def get_thread_messages(
    thread_id: str,
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> dict[str, Any]:
    """
    Get the authoritative message history for a thread.
    
    This endpoint serves as the single source of truth for thread state,
    enabling frontend recovery/reconciliation when real-time sync fails.
    
    Use cases:
    - Initial load/page refresh
    - After reconnection
    - When state seems inconsistent
    
    Args:
        thread_id: The conversation thread ID
        stream_manager: Injected stream manager dependency
    
    Returns:
        Dictionary containing thread_id and list of messages with their metadata
    """
    logger.info(f"Fetching message history for thread: {thread_id}")
    
    # Get the graph from the session
    agent = stream_manager.opey_session.graph
    
    # Build config for the thread
    config = stream_manager.opey_session.build_config({
        'configurable': {
            'thread_id': thread_id,
        }
    })
    
    try:
        # Get current state
        current_state = await agent.aget_state(config)
        
        if not current_state or not current_state.values:
            # Thread doesn't exist yet or has no messages
            return {
                "thread_id": thread_id,
                "messages": [],
                "message_count": 0
            }
        
        # Get messages from state
        messages = current_state.values.get('messages', [])
        
        # Convert LangChain messages to our ChatMessage format
        formatted_messages = []
        for msg in messages:
            try:
                chat_msg = ChatMessage.from_langchain(msg)
                formatted_messages.append({
                    "id": getattr(msg, 'id', None),
                    "type": chat_msg.type,
                    "content": chat_msg.content,
                    "timestamp": getattr(msg, 'timestamp', None),
                    "tool_calls": chat_msg.tool_calls if hasattr(chat_msg, 'tool_calls') else [],
                    "tool_call_id": chat_msg.tool_call_id if hasattr(chat_msg, 'tool_call_id') else None,
                    "tool_status": chat_msg.tool_status if hasattr(chat_msg, 'tool_status') else None,
                })
            except Exception as e:
                logger.warning(f"Failed to convert message to ChatMessage: {e}")
                # Include a minimal representation if conversion fails
                formatted_messages.append({
                    "id": getattr(msg, 'id', None),
                    "type": msg.__class__.__name__,
                    "content": str(msg.content) if hasattr(msg, 'content') else "",
                    "error": f"Conversion failed: {str(e)}"
                })
        
        logger.info(f"Retrieved {len(formatted_messages)} messages for thread {thread_id}")
        
        return {
            "thread_id": thread_id,
            "messages": formatted_messages,
            "message_count": len(formatted_messages)
        }
        
    except Exception as e:
        logger.error(f"Error retrieving thread messages for {thread_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve thread messages: {str(e)}"
        )
