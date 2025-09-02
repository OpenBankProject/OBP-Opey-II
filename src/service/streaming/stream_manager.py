import logging
from typing import AsyncGenerator, Optional, Literal
from langchain_core.runnables.schema import StreamEvent as LangGraphStreamEvent
from langchain_core.messages import ToolMessage
from langgraph.graph.state import CompiledStateGraph

from .events import StreamEvent, StreamEventFactory
from .processors import StreamEventOrchestrator
from schema import StreamInput, ChatMessage
from service.opey_session import OpeySession

logger = logging.getLogger(__name__)


class StreamManager:
    """Main interface for managing streaming responses"""

    def __init__(self, opey_session: OpeySession):
        self.opey_session = opey_session
        self.graph: CompiledStateGraph = opey_session.graph

    async def stream_response(
        self,
        stream_input: StreamInput,
        config: dict
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Main method to stream a response from the agent

        Args:
            stream_input: The input configuration for streaming
            config: LangGraph configuration including thread_id

        Yields:
            StreamEvent: Clean, typed events for the frontend
        """

        thread_id = config.get("configurable", {}).get("thread_id")
        logger.info("Starting stream response", extra={
            "event_type": "stream_start",
            "thread_id": thread_id,
            "stream_tokens": stream_input.stream_tokens,
            "tool_call_approval": stream_input.tool_call_approval.model_dump() if stream_input.tool_call_approval else None,
            "message_length": len(stream_input.message) if stream_input.message else 0
        })

        orchestrator = StreamEventOrchestrator(stream_input)

        try:
            # Parse input for the graph
            if stream_input.tool_call_approval:
                graph_input = None
                logger.debug("Processing tool call approval", extra={
                    "event_type": "tool_approval_processing",
                    "thread_id": thread_id
                })
            else:
                input_message = ChatMessage(type="human", content=stream_input.message)
                graph_input = {"messages": [input_message.to_langchain()]}
                logger.debug("Processing user message", extra={
                    "event_type": "user_message_processing",
                    "thread_id": thread_id,
                    "message_type": input_message.type
                })

            # Stream events from the graph
            kwargs = {
                "input": graph_input,
                "config": config
            }

            event_count = 0
            async for langgraph_event in self.graph.astream_events(**kwargs, version="v2"):
                event_count += 1
                try:
                    # Process each LangGraph event through our orchestrator
                    async for stream_event in orchestrator.process_event(langgraph_event):
                        yield stream_event
                except Exception as e:
                    error_msg = f"Error processing LangGraph event: {str(e)}"
                    logger.error(error_msg, exc_info=True, extra={
                        "event_type": "langgraph_event_processing_error",
                        "thread_id": thread_id,
                        "event_count": event_count,
                        "langgraph_event_type": langgraph_event.get("event"),
                        "langgraph_event_metadata": langgraph_event.get("metadata", {})
                    })
                    yield StreamEventFactory.error(
                        error_message=error_msg,
                        error_code="langgraph_event_error",
                        details={"event_count": event_count, "langgraph_event": langgraph_event}
                    )

            logger.info(f"Processed {event_count} LangGraph events", extra={
                "event_type": "langgraph_events_completed",
                "thread_id": thread_id,
                "event_count": event_count
            })

            # Check for human approval requirement
            async for approval_event in self._handle_approval_if_needed(orchestrator, config):
                yield approval_event

        except Exception as e:
            error_msg = f"Streaming error: {str(e)}"
            logger.error(error_msg, exc_info=True, extra={
                "event_type": "stream_response_error",
                "thread_id": thread_id,
                "stream_tokens": stream_input.stream_tokens,
                "tool_approval": stream_input.tool_call_approval.model_dump() if stream_input.tool_call_approval else None,
            })
            yield StreamEventFactory.error(
                error_message=error_msg,
                error_code="stream_error",
                details={"thread_id": thread_id, "config": config}
            )
        finally:
            # Always send stream end event
            logger.info("Stream response completed", extra={
                "event_type": "stream_end",
                "thread_id": thread_id
            })
            yield StreamEventFactory.stream_end()

    async def _handle_approval_if_needed(
        self,
        orchestrator: StreamEventOrchestrator,
        config: dict
    ) -> AsyncGenerator[StreamEvent, None]:
        """Handle human approval requirements"""

        thread_id = config.get("configurable", {}).get("thread_id")

        try:
            # Get current state to check for interruptions
            logger.error("stream_manager says: GETTING_AGENT_STATE_FOR_APPROVAL_CHECK")
            logger.error(f"stream_manager says: APPROVAL_CHECK_THREAD_ID: {thread_id}")
            logger.error(f"stream_manager says: THREAD_ID_VALIDATION: config={config}")
            logger.error(f"stream_manager says: CHECKPOINTER_INFO: type={type(self.graph.checkpointer).__name__}")
            agent_state = await self.graph.aget_state(config)

            logger.error(f"stream_manager says: APPROVAL_CHECK_STATE: next={agent_state.next}, values={list(agent_state.values.keys()) if agent_state.values else []}")
            logger.error(f"stream_manager says: APPROVAL_CHECK_TASKS: {len(agent_state.tasks)} tasks pending")
            logger.error(f"stream_manager says: APPROVAL_CHECK_METADATA: created_at={getattr(agent_state, 'created_at', 'N/A')}, parent_config={getattr(agent_state, 'parent_config', 'N/A')}")

            logger.debug("Checking for approval requirements", extra={
                "event_type": "approval_check",
                "thread_id": thread_id,
                "has_next": bool(agent_state.next),
                "next_nodes": agent_state.next if agent_state.next else []
            })

            if agent_state.next and "human_review" in agent_state.next:
                logger.error("stream_manager says: HUMAN_REVIEW_DETECTED: Graph is interrupted and waiting for approval")
                logger.error(f"stream_manager says: CHECKPOINT_ID: {getattr(agent_state, 'config', {}).get('configurable', {}).get('checkpoint_id', 'N/A')}")
                messages = agent_state.values.get("messages", [])

                logger.info("Human approval required", extra={
                    "event_type": "approval_required",
                    "thread_id": thread_id,
                    "message_count": len(messages)
                })

                if messages:
                    tool_call_message = messages[-1]

                    if hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls:
                        for tool_call in tool_call_message.tool_calls:
                            # Check if this is a tool that requires approval
                            if self._requires_approval(tool_call):
                                logger.info("Requesting approval for tool call", extra={
                                    "event_type": "approval_request_created",
                                    "thread_id": thread_id,
                                    "tool_name": tool_call["name"],
                                    "tool_call_id": tool_call["id"],
                                    "method": tool_call["args"].get("method", "unknown")
                                })
                                yield StreamEventFactory.approval_request(
                                    tool_name=tool_call["name"],
                                    tool_call_id=tool_call["id"],
                                    tool_input=tool_call["args"],
                                    message=f"Approval required for {tool_call['name']} with {tool_call['args'].get('method', 'unknown')} request"
                                )
                            else:
                                logger.debug("Tool call does not require approval", extra={
                                    "event_type": "approval_not_required",
                                    "thread_id": thread_id,
                                    "tool_name": tool_call["name"],
                                    "tool_call_id": tool_call["id"]
                                })
                else:
                    logger.warning("Human review required but no messages found", extra={
                        "event_type": "approval_no_messages",
                        "thread_id": thread_id
                    })
            else:
                logger.debug("No approval required", extra={
                    "event_type": "approval_not_needed",
                    "thread_id": thread_id
                })

        except Exception as e:
            error_msg = f"Error handling approval check: {str(e)}"
            logger.error(error_msg, exc_info=True, extra={
                "event_type": "approval_handling_error",
                "thread_id": thread_id
            })
            yield StreamEventFactory.error(
                error_message=error_msg,
                error_code="approval_check_error",
                details={"thread_id": thread_id}
            )

    def _requires_approval(self, tool_call: dict) -> bool:
        """Determine if a tool call requires human approval"""

        # Tools that require approval (non-GET OBP requests)
        if tool_call["name"] == "obp_requests":
            method = tool_call["args"].get("method", "").upper()
            requires_approval = method != "GET"

            logger.debug("Approval decision for OBP request", extra={
                "event_type": "approval_decision",
                "tool_name": tool_call["name"],
                "tool_call_id": tool_call["id"],
                "method": method,
                "requires_approval": requires_approval
            })

            return requires_approval

        logger.debug("Tool does not require approval", extra={
            "event_type": "approval_decision",
            "tool_name": tool_call["name"],
            "tool_call_id": tool_call["id"],
            "requires_approval": False
        })

        return False

    # TODO: There must be a better way to do this... Harnessing OBP Error Response Patterns would be a start, Or finally getting a proper python SDK working...
    def _analyze_obp_response_status(self, response_content: str) -> Literal["success", "error"]:
        """Analyze OBP API response content to determine success/error status"""
        try:
            # Handle both string and dict responses
            if isinstance(response_content, str):
                import json
                try:
                    response_data = json.loads(response_content)
                except json.JSONDecodeError:
                    # If not JSON, check for common error patterns in string
                    if any(error_indicator in response_content.lower() for error_indicator in ['error:', 'exception(', 'failed', 'unauthorized', 'forbidden', 'obp-', 'value too long', 'http 4', 'http 5']):
                        return "error"
                    return "success"
            else:
                response_data = response_content

            # Check for explicit error indicators
            if isinstance(response_data, dict):
                # Common OBP error patterns
                if 'error' in response_data or 'message' in response_data:
                    return "error"

                # OBP specific error patterns
                if 'failMsg' in response_data or 'failCode' in response_data:
                    return "error"

                # HTTP status code indicators
                if 'code' in response_data:
                    code = response_data['code']
                    if isinstance(code, (int, str)) and str(code).startswith(('4', '5')):
                        return "error"

                # Check for successful creation/update patterns
                if any(success_key in response_data for success_key in ['bank_id', 'user_id', 'account_id', 'transaction_id']):
                    return "success"

                # Check for successful list responses
                if any(list_key in response_data for list_key in ['banks', 'accounts', 'transactions', 'users']):
                    return "success"

            # Default to success if no error indicators found
            return "success"

        except Exception as e:
            logger.warning(f"Error analyzing OBP response status: {e}")
            # Default to error if analysis fails
            return "error"

    async def continue_after_approval(
        self,
        approval_stream_input: StreamInput
    ) -> AsyncGenerator[StreamEvent, None]:
        """Continue streaming after human approval/denial"""

        if not approval_stream_input.tool_call_approval:
            logger.error("Tool call approval data is missing", extra={'approval_stream_input': approval_stream_input.model_dump()})
            raise ValueError("Tool call approval data is required to continue after approval.",)

        approved = approval_stream_input.tool_call_approval.approval == "approve"
        thread_id = approval_stream_input.thread_id
        tool_call_id = approval_stream_input.tool_call_approval.tool_call_id

        #TODO: I think we might want to start passing a langchain RunnableConfig to all functions that need to stream or invoke
        # This allows us more flexibility, not just passing thread_id but other config options too
        config = {"configurable": {"thread_id": thread_id}}

        logger.info(f"continuing after approval for thread ID: {thread_id}")
        logger.info(f"stream_manager says: APPROVED_TOOL_CALL_ID: {tool_call_id}")


        logger.info("Continuing after approval decision", extra={
            'approval_stream_input': approval_stream_input.model_dump()
        })

        try:
            if approved:
                logger.info(f"stream_manager says: APPROVAL_GRANTED: tool_call_id={tool_call_id}, thread_id={thread_id}")
                logger.info("Tool call approved, continuing execution", extra={
                    "event_type": "tool_approved",
                    "thread_id": thread_id,
                    "tool_call_id": tool_call_id
                })
                # Resume from interrupt - no state change needed for approval
                pass
            else:
                logger.error(f"stream_manager says: APPROVAL_DENIED: tool_call_id={tool_call_id}, thread_id={thread_id}")
                logger.info("Tool call denied, injecting denial message", extra={
                    "event_type": "tool_denied",
                    "thread_id": thread_id,
                    "tool_call_id": tool_call_id
                })
                # Inject a denial message
                from langchain_core.messages import ToolMessage
                logger.info("stream_manager says: injecting tool denial message into graph state")
                update_result = await self.graph.aupdate_state(
                    config,
                    {"messages": [ToolMessage(
                        content="User denied request to OBP API",
                        tool_call_id=tool_call_id
                    )]},
                    as_node="tools",
                )
                logger.debug(f"stream_manager says: DENIAL_MESSAGE_INJECTED: update_result={update_result}")

            # Continue streaming the response
            orchestrator = StreamEventOrchestrator(stream_input)

            logger.info("Starting astream_events loop for approval continuation", extra={
                "event_type": "approval_continuation_astream_start",
                "thread_id": thread_id,
                "tool_call_id": tool_call_id
            })

            import time
            start_time = time.time()
            last_event_time = start_time

            # Debug: Check current graph state before continuation
            try:
                logger.error("stream_manager says: Getting graph state for debugging before astream continuation")
                # Check state immediately after approval processing
                logger.error(f"stream_manager says: PRE_CONTINUATION_CHECK: approved={approved}")
                logger.error(f"stream_manager says: PRE_CONTINUATION_CONFIG: {config}")
                logger.error(f"stream_manager says: PRE_CONTINUATION_CHECKPOINTER: {type(self.graph.checkpointer).__name__}")

                # Check if checkpointer has any saved states
                try:
                    checkpoint_list = []
                    async for checkpoint_tuple in self.graph.checkpointer.alist(config):
                        checkpoint_list.append(f"checkpoint_id={checkpoint_tuple.config.get('configurable', {}).get('checkpoint_id', 'N/A')}")
                    logger.error(f"stream_manager says: AVAILABLE_CHECKPOINTS: {checkpoint_list}")
                except Exception as checkpoint_error:
                    logger.error(f"stream_manager says: CHECKPOINT_LIST_ERROR: {str(checkpoint_error)}")

                current_state = await self.graph.aget_state(config)
                logger.error(f"stream_manager says: GRAPH_STATE_DEBUG: next={current_state.next}, values={current_state.values}")
                logger.error(f"stream_manager says: GRAPH_STATE_TASKS: {len(current_state.tasks)} tasks pending")
                logger.error(f"stream_manager says: GRAPH_STATE_METADATA: created_at={getattr(current_state, 'created_at', 'N/A')}, parent_config={getattr(current_state, 'parent_config', 'N/A')}")

                # Additional debugging for empty state
                if not current_state.next and not current_state.values:
                    logger.error("stream_manager says: WARNING - Graph state is completely empty (no next nodes, no values)")
                    logger.error(f"stream_manager says: EMPTY_STATE_DETAILS: config={config}")
                    logger.error(f"stream_manager says: EMPTY_STATE_DETAILS: thread_id={thread_id}")
                    logger.error(f"stream_manager says: EMPTY_STATE_DETAILS: tool_call_id={tool_call_id}")
                    logger.error(f"stream_manager says: EMPTY_STATE_DETAILS: approved={approved}")

                # Log state values breakdown if they exist
                if current_state.values:
                    for key, value in current_state.values.items():
                        logger.error(f"stream_manager says: STATE_VALUE_DEBUG: {key} = {type(value).__name__} (len={len(value) if hasattr(value, '__len__') else 'N/A'})")

                # Log next nodes details
                if current_state.next:
                    logger.error(f"stream_manager says: NEXT_NODES_DEBUG: {list(current_state.next)}")
                else:
                    logger.error("stream_manager says: NEXT_NODES_DEBUG: No next nodes scheduled")

            except Exception as e:
                logger.error(f"stream_manager says: GRAPH_STATE_ERROR: {str(e)}")
                logger.error("stream_manager says: Failed to get graph state for debugging", exc_info=True)

            event_count = 0
            logger.info("stream_manager says: Bypassing human_review node to continue after approval")

            # Bypass the problematic human_review interrupt continuation
            # by manually updating state and proceeding to tools node
            try:
                # Check original state before bypass
                pre_bypass_state = await self.graph.aget_state(config)
                if pre_bypass_state.values and "messages" in pre_bypass_state.values:
                    messages = pre_bypass_state.values["messages"]
                    logger.error(f"stream_manager says: PRE_BYPASS_STATE - Found {len(messages)} messages")
                    last_message = messages[-1] if messages else None
                    if last_message and hasattr(last_message, 'tool_calls'):
                        tool_calls = last_message.tool_calls
                        logger.error(f"stream_manager says: PRE_BYPASS_STATE - Last message has {len(tool_calls)} tool calls")
                        for i, tc in enumerate(tool_calls):
                            logger.error(f"stream_manager says: PRE_BYPASS_STATE - Tool call {i}: id={tc.get('id', 'no-id')}, name={tc.get('name', 'no-name')}")
                    else:
                        logger.error("stream_manager says: PRE_BYPASS_STATE - No tool calls found in last message")

                # Mark human_review as completed with approval
                await self.graph.aupdate_state(
                    config,
                    {"current_state": "approved"},
                    as_node="human_review"
                )
                logger.info("stream_manager says: Human review bypassed, proceeding to tools execution")

                # Continue graph execution from tools node
                logger.error("stream_manager says: APPROVAL_FLOW - Starting astream after bypass")
                async for graph_chunk in self.graph.astream(
                    input=None,
                    config=config
                ):
                    event_count += 1
                    current_time = time.time()
                    time_since_start = current_time - start_time
                    time_since_last = current_time - last_event_time

                    logger.error(f"stream_manager says: APPROVAL_FLOW - Received graph_chunk #{event_count}")
                    logger.error(f"stream_manager says: APPROVAL_FLOW - Graph chunk type: {type(graph_chunk)}")
                    if isinstance(graph_chunk, dict):
                        logger.error(f"stream_manager says: APPROVAL_FLOW - Graph chunk keys: {list(graph_chunk.keys())}")
                    last_event_time = current_time



                    logger.info("Processing post-approval graph chunk", extra={
                        "event_type": "post_approval_graph_chunk",
                        "thread_id": thread_id,
                        "event_count": event_count,
                        "graph_nodes": list(graph_chunk.keys()) if graph_chunk else [],
                        "time_since_start": round(time_since_start, 2),
                        "time_since_last_event": round(time_since_last, 2)
                    })

                # Log warning if tool execution is taking too long
                if time_since_start > 30 and event_count > 20:
                    logger.warning("Long-running tool execution detected", extra={
                        "event_type": "long_running_tool_warning",
                        "thread_id": thread_id,
                        "tool_call_id": tool_call_id,
                        "time_running": round(time_since_start, 2),
                        "events_processed": event_count
                    })

                try:
                    # Process graph chunk and extract meaningful events
                    for node_name, node_output in graph_chunk.items():
                        logger.error(f"stream_manager says: APPROVAL_FLOW_DEBUG - Processing node: {node_name}")
                        logger.error(f"stream_manager says: APPROVAL_FLOW_DEBUG - Node output keys: {list(node_output.keys()) if isinstance(node_output, dict) else 'Not a dict'}")
                        logger.error(f"stream_manager says: NODE_NAME_CHECK - Checking if '{node_name}' == 'tools': {node_name == 'tools'}")

                        if isinstance(node_output, dict) and 'messages' in node_output:
                            messages = node_output['messages']
                            # Handle both single message and list of messages
                            if isinstance(messages, list):
                                logger.error(f"stream_manager says: APPROVAL_FLOW_DEBUG - Found {len(messages)} messages in {node_name} node")
                                for i, msg in enumerate(messages):
                                    logger.error(f"stream_manager says: APPROVAL_FLOW_DEBUG - Message {i}: type={type(msg).__name__}, has_content={hasattr(msg, 'content')}, has_tool_call_id={hasattr(msg, 'tool_call_id')}")
                            else:
                                logger.error(f"stream_manager says: APPROVAL_FLOW_DEBUG - Found single message in {node_name} node: type={type(messages).__name__}, has_content={hasattr(messages, 'content')}")

                        logger.info(f"Processing node: {node_name}", extra={
                            "event_type": "node_processing",
                            "node_name": node_name,
                            "thread_id": thread_id
                        })

                        # Handle tools node - this is where obp_requests executes
                        if node_name == "tools":
                            logger.error("stream_manager says: TOOLS_NODE_EXECUTED - Processing tool results")
                            messages = node_output.get("messages", [])
                            # Ensure messages is always a list for tools node processing
                            if not isinstance(messages, list):
                                messages = [messages]
                            logger.error(f"stream_manager says: TOOLS_NODE_DEBUG - Found {len(messages)} messages")

                            # Check if any messages have tool attributes
                            tool_messages_found = 0
                            for i, message in enumerate(messages):
                                logger.error(f"stream_manager says: TOOLS_MSG_DEBUG - Message {i} - type: {type(message).__name__}")

                                # Check all attributes to debug the message structure
                                attrs = dir(message)
                                relevant_attrs = [attr for attr in attrs if not attr.startswith('_') and attr in ['tool_call_id', 'content', 'name', 'tool_calls']]
                                logger.error(f"stream_manager says: TOOLS_MSG_DEBUG - Message {i} - relevant attrs: {relevant_attrs}")

                                if hasattr(message, 'tool_call_id'):
                                    logger.error(f"stream_manager says: TOOLS_MSG_DEBUG - Message {i} - tool_call_id: {message.tool_call_id}")
                                if hasattr(message, 'content'):
                                    content_preview = str(message.content)[:200] + "..." if len(str(message.content)) > 200 else str(message.content)
                                    logger.error(f"stream_manager says: TOOLS_MSG_DEBUG - Message {i} - content: {content_preview}")

                                if isinstance(message, ToolMessage):
                                    tool_messages_found += 1
                                    logger.error(f"stream_manager says: TOOLS_MSG_MATCH - Found tool message {tool_messages_found}: {message.tool_call_id}")

                                    # Check if this tool_call_id matches the approved tool_call_id
                                    logger.error(f"stream_manager says: TOOL_ID_MATCH_CHECK - Comparing message.tool_call_id='{message.tool_call_id}' with approved tool_call_id='{tool_call_id}'")

                                    if message.tool_call_id != tool_call_id:
                                        logger.error(f"stream_manager says: TOOL_ID_MISMATCH - Skipping tool message with different ID")
                                        continue

                                    # Generate tool_start event first (might be missing in approval flow)
                                    # Get the original tool call from the pre-bypass state
                                    original_tool_input = {"method": "unknown", "path": "unknown"}
                                    if 'graph_chunk' in locals() and node_name == "tools":
                                        # Try to extract tool input from the graph state
                                        pre_bypass_state = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
                                        if pre_bypass_state.values and "messages" in pre_bypass_state.values:
                                            messages_state = pre_bypass_state.values["messages"]
                                            for msg in reversed(messages_state):
                                                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                                    for tc in msg.tool_calls:
                                                        if tc.get('id') == message.tool_call_id:
                                                            original_tool_input = tc.get('args', original_tool_input)
                                                            break

                                    logger.error("stream_manager says: TOOL_START_CHECK - Generating tool_start event for approval flow")
                                    tool_start_event = StreamEventFactory.tool_start(
                                        tool_name="obp_requests",
                                        tool_call_id=message.tool_call_id,
                                        tool_input=original_tool_input
                                    )
                                    logger.error("stream_manager says: TOOL_START_YIELDING - About to yield tool_start event")
                                    yield tool_start_event
                                    logger.error("stream_manager says: TOOL_START_YIELDED - Successfully yielded tool_start event")

                                    # Enhanced OBP API response analysis
                                    status = self._analyze_obp_response_status(message.content)
                                    logger.error(f"stream_manager says: TOOL_RESULT - {message.tool_call_id} -> Status: {status}")
                                    logger.error(f"stream_manager says: TOOL_EVENT_CREATION - Creating tool_end event for {message.tool_call_id}")

                                    # If this is an error, emit error event first for immediate Portal visibility
                                    if status == "error":
                                        logger.error(f"stream_manager says: TOOL_ERROR_DETECTED - Emitting error event for {message.tool_call_id}")

                                        # Format user-friendly error message
                                        if isinstance(message.content, str) and "OBP API error" in message.content:
                                            # Extract the actual error message from the exception string
                                            if "): " in message.content:
                                                actual_error = message.content.split("): ", 1)[1]
                                                if actual_error.endswith("')\n Please fix your mistakes."):
                                                    actual_error = actual_error.replace("')\n Please fix your mistakes.", "")
                                            else:
                                                actual_error = message.content
                                            user_error_msg = f"API Error: {actual_error}"
                                        else:
                                            user_error_msg = f"Tool execution failed: {message.content}"

                                        error_event = StreamEventFactory.error(
                                            error_message=user_error_msg,
                                            error_code="tool_execution_error",
                                            details={"tool_call_id": message.tool_call_id, "tool_name": "obp_requests", "tool_output": message.content}
                                        )
                                        logger.error(f"stream_manager says: TOOL_ERROR_YIELDING - About to yield error event: {error_event.model_dump_json()}")
                                        yield error_event
                                        logger.error(f"stream_manager says: TOOL_ERROR_YIELDED - Successfully yielded error event")

                                    # Explicit cast to ensure type compatibility
                                    status_typed: Literal["success", "error"] = status

                                    tool_end_event = StreamEventFactory.tool_end(
                                        tool_name="obp_requests",
                                        tool_call_id=message.tool_call_id,
                                        tool_output=message.content,
                                        status=status_typed
                                    )
                                    logger.error("stream_manager says: TOOL_EVENT_YIELDING - About to yield tool_end event")
                                    yield tool_end_event
                                    logger.error("stream_manager says: TOOL_EVENT_YIELDED - Successfully yielded tool_end event")
                                else:
                                    logger.error(f"stream_manager says: TOOLS_MSG_SKIP - Message {i} does not match tool pattern")

                            logger.error(f"stream_manager says: TOOLS_NODE_SUMMARY - Total tool messages processed: {tool_messages_found}")
                            if tool_messages_found == 0:
                                logger.error("stream_manager says: TOOLS_NODE_WARNING - No tool messages found with both tool_call_id and content")

                        # Handle assistant responses
                        elif node_name == "opey":
                            messages = node_output.get("messages", [])
                            # Handle single message or list of messages
                            if not isinstance(messages, list):
                                messages = [messages]
                            for message in messages:
                                if hasattr(message, 'content') and message.content:
                                    # Assistant response - stream as tokens and complete
                                    message_id = getattr(message, 'id', f'msg_{event_count}')

                                    # Start assistant response
                                    yield StreamEventFactory.assistant_start(message_id=message_id)

                                    # Stream content as tokens (simulate streaming)
                                    content = message.content
                                    for i, char in enumerate(content):
                                        if i % 10 == 0 or i == len(content) - 1:  # Send every 10 chars or last char
                                            token_content = content[max(0, i-9):i+1]
                                            yield StreamEventFactory.assistant_token(
                                                content=token_content,
                                                message_id=message_id
                                            )

                                    # Complete assistant response
                                    yield StreamEventFactory.assistant_complete(
                                        content=content,
                                        message_id=message_id
                                    )

                except Exception as e:
                    error_msg = f"Error processing post-approval graph chunk: {str(e)}"
                    logger.error(error_msg, exc_info=True, extra={
                        "event_type": "post_approval_chunk_error",
                        "thread_id": thread_id,
                        "tool_call_id": tool_call_id,
                        "event_count": event_count,
                        "graph_chunk": str(graph_chunk) if 'graph_chunk' in locals() else "N/A"
                    })
                    yield StreamEventFactory.error(
                        error_message=error_msg,
                        error_code="post_approval_event_error",
                        details={
                            "thread_id": thread_id,
                            "tool_call_id": tool_call_id,
                            "event_count": event_count
                        }
                    )

                logger.info("stream_manager says: Approval continuation completed successfully")
            except Exception as astream_error:
                logger.error(f"stream_manager says: Error in approval continuation: {str(astream_error)}")
                logger.error("stream_manager says: Exception during graph continuation", exc_info=True)

                raise astream_error

            logger.info("Approval continuation astream loop ended", extra={
                "event_type": "approval_continuation_astream_end",
                "thread_id": thread_id,
                "tool_call_id": tool_call_id,
                "total_graph_chunks_processed": event_count
            })

            logger.info("Approval continuation completed", extra={
                "event_type": "approval_continuation_completed",
                "thread_id": thread_id,
                "tool_call_id": tool_call_id,
                "approved": approved,
                "total_graph_chunks_processed": event_count
            })

        except Exception as e:
            error_msg = f"Error continuing after approval: {str(e)}"
            logger.error(error_msg, exc_info=True, extra={
                "event_type": "approval_continuation_error",
                "thread_id": thread_id,
                "tool_call_id": tool_call_id,
                "approved": approved
            })
            yield StreamEventFactory.error(
                error_message=error_msg,
                error_code="approval_continuation_error",
                details={
                    "thread_id": thread_id,
                    "tool_call_id": tool_call_id,
                    "approved": approved
                }
            )
        finally:
            logger.info("Approval continuation stream ended", extra={
                "event_type": "approval_continuation_stream_end",
                "thread_id": thread_id,
                "tool_call_id": tool_call_id
            })
            yield StreamEventFactory.stream_end()

    def to_sse_format(self, event: StreamEvent) -> str:
        """Convert a stream event to SSE format"""
        return event.to_sse_data()
