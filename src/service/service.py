import json
import os
import warnings
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.schema import StreamEvent
from langchain_core.messages import ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langsmith import Client as LangsmithClient

from agent import opey_graph
from fastapi import WebSocket
from schema import (
    ChatMessage,
    Feedback,
    FeedbackResponse,
    StreamInput,
    UserInput,
    convert_message_content_to_string,
    ToolCallApproval,
)

#logging.basicConfig(level=logging.DEBUG)
#logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Construct agent with Sqlite checkpointer
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as saver:
        opey_graph.checkpointer = saver
        app.state.agent = opey_graph
        yield
    # context manager will clean up the AsyncSqliteSaver on exit


app = FastAPI(lifespan=lifespan)

# TODO: change to implement our own authentication checking (also decide what auth to use)
# NOTE: will be different when we use consents rather than a secret
@app.middleware("http")
async def check_auth_header(request: Request, call_next: Callable) -> Response:
    if auth_secret := os.getenv("AUTH_SECRET"):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(status_code=401, content="Missing or invalid token")
        if auth_header[7:] != auth_secret:
            return Response(status_code=401, content="Invalid token")
    return await call_next(request)

def _parse_input(user_input: UserInput) -> tuple[dict[str, Any], str]:
    run_id = uuid4()
    thread_id = user_input.thread_id or str(uuid4())
    # If this is a tool call approval, we don't need to send any input to the agent.
    if user_input.is_tool_call_approval:
        _input = None
    else:
        input_message = ChatMessage(type="human", content=user_input.message)
        _input = {"messages": [input_message.to_langchain()]}
    
    kwargs = {
        "input": _input,
        "config": RunnableConfig(
            configurable={"thread_id": thread_id, "model": user_input.model}, run_id=run_id
        ),
    }
    return kwargs, run_id, thread_id


def _remove_tool_calls(content: str | list[str | dict]) -> str | list[str | dict]:
    """Remove tool calls from content."""
    if isinstance(content, str):
        return content
    # Currently only Anthropic models stream tool calls, using content item type tool_use.
    return [
        content_item
        for content_item in content
        if isinstance(content_item, str) or content_item["type"] != "tool_use"
    ]

# Global dictionary to track user approvals
_approval_condition = asyncio.Condition()  # Single instance
_pending_approvals = {}

async def wait_for_user_approval(thread_id: str) -> str:
    print(f"[Debug] Wait for approval event loop: {id(asyncio.get_running_loop())}")
    async with _approval_condition:
        print(f"[Waiter] Waiting for approval of {thread_id}")
        while thread_id not in _pending_approvals.keys():
            await _approval_condition.wait()
            print(f"[Waiter] Woke up for {thread_id}, checking condition")
            print(f"[Waiter] Pending approvals: {_pending_approvals}")
        print(f"[Waiter] Returning {_pending_approvals[thread_id]}")
        return _pending_approvals.pop(thread_id)
    

async def _process_stream_event(event: StreamEvent, user_input: StreamInput | ToolCallApproval, run_id: str) -> AsyncGenerator[str, None]:
    """Helper to process stream events consistently"""
    if not event:
        return
    
    # Handle messages after node execution
    if (
        event["event"] == "on_chain_end"
        and any(t.startswith("graph:step:") for t in event.get("tags", []))
        and event["data"].get("output") is not None
        and "messages" in event["data"]["output"]
        and event["metadata"].get("langgraph_node", "") not in ["human_review", "summarize_conversation"]
    ):
        new_messages = event["data"]["output"]["messages"]
        if not isinstance(new_messages, list):
            new_messages = [new_messages]

        # This is a proper hacky way to make sure that no messages are sent from the retreiaval decider node
        if event["metadata"].get("langgraph_node", "") == "retrieval_decider":
            print(f"Retrieval decider node returned text content, erasing...")
            erase_content = True
        else:
            erase_content = False
            
        for message in new_messages:
            if erase_content:
                message.content = ""
            try:
                chat_message = ChatMessage.from_langchain(message)
                chat_message.run_id = str(run_id)
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Error parsing message: {e}'})}\n\n"
                continue

            if not (chat_message.type == "human" and chat_message.content == user_input.message):
                chat_message.pretty_print()
                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

    # Handle tokens streamed from LLMs
    if (
        event["event"] == "on_chat_model_stream"
        and user_input.stream_tokens
        and event['metadata'].get('langgraph_node', '') != "transform_query"
        and event['metadata'].get('langgraph_node', '') != "retrieval_decider"
        and event['metadata'].get('langgraph_node', '') != "summarize_conversation"
    ):
        content = _remove_tool_calls(event["data"]["chunk"].content)
        if content:
            yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"


@app.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """
    Invoke the agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    """
    agent: CompiledStateGraph = app.state.agent
    kwargs, run_id = _parse_input(user_input)
    try:
        response = await agent.ainvoke(**kwargs)
        output = ChatMessage.from_langchain(response["messages"][-1])
        output.run_id = str(run_id)
        return output
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def message_generator(user_input: StreamInput) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    agent: CompiledStateGraph = app.state.agent
    kwargs, run_id, thread_id = _parse_input(user_input)
    thread = {"configurable": {"thread_id": thread_id}}

    print(f"------------START STREAM-----------\n\n")
    # Process streamed events from the graph and yield messages over the SSE stream.
    async for event in agent.astream_events(**kwargs, version="v2"):
        async for msg in _process_stream_event(event, user_input, run_id):
            yield msg

    # Interruption for human in the loop
    # Wait for user approval via HTTP request
    agent_state = await agent.aget_state(thread)
    messages = agent_state.values.get("messages", [])
    print(f"next node: {agent_state.next}")
    tool_call_message = messages[-1] if messages else None
    
    if not tool_call_message or not tool_call_message.tool_calls:
        pass
    else:
        print(f"Tool call message: {tool_call_message}\n")
        tool_call = tool_call_message.tool_calls[0]
        print(f"Waiting for approval of tool call: {tool_call}\n")

        tool_approval_message = ChatMessage(type="tool", tool_approval_request=True, tool_call_id=tool_call["id"], content="", tool_calls=[tool_call])

        yield f"data: {json.dumps({'type': 'message', "content": tool_approval_message.model_dump()})}\n\n"
    

    yield "data: [DONE]\n\n"


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


@app.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream_agent(user_input: StreamInput) -> StreamingResponse:
    """
    Stream the agent's response to a user input, including intermediate messages and tokens.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    """
    return StreamingResponse(message_generator(user_input), media_type="text/event-stream")


@app.post("/approval/{thread_id}", response_class=StreamingResponse, responses=_sse_response_example())
async def user_approval(user_approval_response: ToolCallApproval, thread_id: str) -> StreamingResponse:
    print(f"[DEBUG] Approval endpoint user_response: {user_approval_response}\n")
    
    agent: CompiledStateGraph = app.state.agent

    agent_state = await agent.aget_state({"configurable": {"thread_id": thread_id}})

    if user_approval_response.approval == "deny":
        # Answer as if we were the obp requests tool node
        await agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [ToolMessage(content="User denied request to OBP API", tool_call_id=user_approval_response.tool_call_id)]},
            as_node="obp_requests_tools",
        )
    else:
        # If approved, just continue to the OBP requests node
        await agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            values=None,
            as_node="human_review",
        )

    print(f"[DEBUG] Agent state: {agent_state}\n")
    
    user_input = StreamInput(
        message="",
        model="",
        thread_id=thread_id,
        is_tool_call_approval=True,
    )


    return StreamingResponse(message_generator(user_input), media_type="text/event-stream")


@app.post("/feedback")
async def feedback(feedback: Feedback) -> FeedbackResponse:
    """
    Record feedback for a run to LangSmith.

    This is a simple wrapper for the LangSmith create_feedback API, so the
    credentials can be stored and managed in the service rather than the client.
    See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
    """
    client = LangsmithClient()
    kwargs = feedback.kwargs or {}
    client.create_feedback(
        run_id=feedback.run_id,
        key=feedback.key,
        score=feedback.score,
        **kwargs,
    )
    return FeedbackResponse()