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
                # Handle approval/denial
                approved = stream_input.tool_call_approval.approval == "approve"
                tool_call_id = stream_input.tool_call_approval.tool_call_id
                
                if approved:
                    logger.info(f"Tool call approved: {tool_call_id}", extra={
                        "event_type": "tool_approved",
                        "thread_id": thread_id,
                        "tool_call_id": tool_call_id
                    })
                    # For approval, just continue - no state change needed
                    graph_input = None
                else:
                    logger.info(f"Tool call denied: {tool_call_id}", extra={
                        "event_type": "tool_denied", 
                        "thread_id": thread_id,
                        "tool_call_id": tool_call_id
                    })
                    # Inject denial message into graph state
                    await self.graph.aupdate_state(
                        config,
                        {"messages": [ToolMessage(
                            content="User denied request to OBP API",
                            tool_call_id=tool_call_id
                        )]},
                        as_node="tools"
                    )
                    graph_input = None
                    
                logger.debug("Processing tool call approval", extra={
                    "event_type": "tool_approval_processing",
                    "thread_id": thread_id,
                    "approved": approved
                })
            else:
                # Regular user message
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

            # Check for human approval requirement (except when the input is a tool approval response)
            if not stream_input.tool_call_approval:
                async for approval_event in self._handle_approval(config):
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

    async def _handle_approval(
        self,
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

            if not agent_state.next or "human_review" not in agent_state.next:
                logger.debug("No human approval required")
                return
            
            messages = agent_state.values.get("messages", [])
            if not messages:
                logger.warning("Human review required but no messages found")
                return
            
            tool_call_message = messages[-1]
            if not (hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls):
                logger.warning("No tool calls found in the latest message")
                return
            
            for tool_call in tool_call_message.tool_calls:
                if not self._requires_approval(tool_call):
                    logger.debug("Tool call does not require approval", extra={
                        "event_type": "approval_not_required",
                        "thread_id": thread_id,
                        "tool_name": tool_call["name"],
                        "tool_call_id": tool_call["id"]
                    })
                    continue

                method = tool_call["args"].get("method", "unknown")
                logger.info("Requesting approval for tool call", extra={
                    "event_type": "approval_request_created",
                    "thread_id": thread_id,
                    "tool_name": tool_call["name"],
                    "tool_call_id": tool_call["id"],
                    "method": method
                })

                yield StreamEventFactory.approval_request(
                    tool_name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                    tool_input=tool_call["args"],
                    message=f"Approval required for {tool_call['name']} with {method} request"
                )

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

    def to_sse_format(self, event: StreamEvent) -> str:
        """Convert a stream event to SSE format"""
        return event.to_sse_data()
