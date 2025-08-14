import logging
from typing import AsyncGenerator, Optional
from langchain_core.runnables.schema import StreamEvent as LangGraphStreamEvent
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
            "is_tool_approval": stream_input.is_tool_call_approval,
            "message_length": len(stream_input.message) if stream_input.message else 0
        })

        orchestrator = StreamEventOrchestrator(stream_input)

        try:
            # Parse input for the graph
            if stream_input.is_tool_call_approval:
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
                "is_tool_approval": stream_input.is_tool_call_approval
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
            agent_state = await self.graph.aget_state(config)

            logger.debug("Checking for approval requirements", extra={
                "event_type": "approval_check",
                "thread_id": thread_id,
                "has_next": bool(agent_state.next),
                "next_nodes": agent_state.next if agent_state.next else []
            })

            if agent_state.next and "human_review" in agent_state.next:
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

    async def continue_after_approval(
        self,
        thread_id: str,
        tool_call_id: str,
        approved: bool,
        stream_input: StreamInput
    ) -> AsyncGenerator[StreamEvent, None]:
        """Continue streaming after human approval/denial"""

        config = {"configurable": {"thread_id": thread_id}}

        logger.info("Continuing after approval decision", extra={
            "event_type": "approval_continuation_start",
            "thread_id": thread_id,
            "tool_call_id": tool_call_id,
            "approved": approved
        })

        try:
            if approved:
                logger.info("Tool call approved, continuing execution", extra={
                    "event_type": "tool_approved",
                    "thread_id": thread_id,
                    "tool_call_id": tool_call_id
                })
                # Resume from interrupt - no state change needed for approval
                pass
            else:
                logger.info("Tool call denied, injecting denial message", extra={
                    "event_type": "tool_denied",
                    "thread_id": thread_id,
                    "tool_call_id": tool_call_id
                })
                # Inject a denial message
                from langchain_core.messages import ToolMessage
                await self.graph.aupdate_state(
                    config,
                    {"messages": [ToolMessage(
                        content="User denied request to OBP API",
                        tool_call_id=tool_call_id
                    )]},
                    as_node="tools",
                )

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
                current_state = await self.graph.aget_state(config)
                logger.error(f"🔍 GRAPH_STATE_DEBUG: next={current_state.next}, values={current_state.values}")
                logger.error(f"🔍 GRAPH_STATE_TASKS: {len(current_state.tasks)} tasks pending")
            except Exception as e:
                logger.error(f"🔍 GRAPH_STATE_ERROR: {str(e)}")

            event_count = 0
            # Use astream to continue the interrupted graph execution from checkpoint
            # For interrupted graphs, we need to provide empty input to continue
            async for graph_chunk in self.graph.astream(
                input={},
                config=config
            ):
                event_count += 1
                current_time = time.time()
                time_since_start = current_time - start_time
                time_since_last = current_time - last_event_time
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
                        logger.info(f"Processing node: {node_name}", extra={
                            "event_type": "node_processing",
                            "node_name": node_name,
                            "thread_id": thread_id
                        })
                        
                        # Handle tools node - this is where obp_requests executes
                        if node_name == "tools":
                            logger.error(f"🎯 TOOLS_NODE_EXECUTED: Processing tool results")
                            messages = node_output.get("messages", [])
                            for message in messages:
                                if hasattr(message, 'tool_call_id') and hasattr(message, 'content'):
                                    # Tool execution completed - create tool_end event
                                    logger.error(f"🚀 TOOL_RESULT: {message.tool_call_id} -> {message.content}")
                                    tool_end_event = StreamEventFactory.tool_end(
                                        tool_name="obp_requests",
                                        tool_call_id=message.tool_call_id,
                                        tool_output=message.content,
                                        status="success" if not message.content.startswith("Error") else "error"
                                    )
                                    yield tool_end_event
                        
                        # Handle assistant responses
                        elif node_name == "opey":
                            messages = node_output.get("messages", [])
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
