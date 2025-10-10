import logging
from typing import AsyncGenerator, Optional, Literal
from langchain_core.runnables.schema import StreamEvent as LangGraphStreamEvent
from langchain_core.messages import ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langchain_core.runnables import RunnableConfig

from .events import StreamEvent, StreamEventFactory
from .processors import StreamEventOrchestrator
from schema import StreamInput, ChatMessage
from service.opey_session import OpeySession
from .orchestrator_repository import orchestrator_repository

logger = logging.getLogger(__name__)


class StreamManager:
    """Main interface for managing streaming responses"""

    def __init__(self, opey_session: OpeySession):
        self.opey_session = opey_session
        self.graph: CompiledStateGraph = opey_session.graph

    async def stream_response(
        self,
        stream_input: StreamInput,
        config: RunnableConfig
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

        orchestrator = orchestrator_repository.get_or_create(thread_id, stream_input)

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
            last_event = None
            async for langgraph_event in self.graph.astream_events(**kwargs, version="v2"):
                event_count += 1
                last_event = langgraph_event
                
                # Check if this event contains interrupt information
                if langgraph_event.get("event") == "on_chain_end":
                    event_data = langgraph_event.get("data", {})
                    output = event_data.get("output", {})
                    if "__interrupt__" in output:
                        logger.info(f"Found __interrupt__ in stream event: {output['__interrupt__']}")
                
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

            # After streaming completes, check the final state for interrupts
            # According to LangGraph docs, __interrupt__ appears in the state after stream ends
            logger.info("Stream completed, checking for interrupts...")
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
        config: RunnableConfig
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Handle human approval requirements by checking for LangGraph interrupts.
        
        According to LangGraph docs, after astream_events() completes:
        - The state will contain '__interrupt__' key if interrupt() was called
        - We extract the interrupt payload and send it to frontend
        - User will resume with Command(resume=...) in a subsequent request
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        approval_manager = config.get("configurable", {}).get("approval_manager")

        try:
            # Get current state to check for interruptions
            # According to LangGraph docs, __interrupt__ appears in state.values after stream ends
            agent_state = await self.graph.aget_state(config)

            logger.info(f"Agent state details:")
            logger.info(f"  - Next nodes: {agent_state.next}")
            logger.info(f"  - Tasks: {len(agent_state.tasks) if agent_state.tasks else 0} tasks")
            logger.info(f"  - Has __interrupt__ in values: {'__interrupt__' in agent_state.values}")
            
            # Collect all interrupts from tasks
            interrupts = []
            if agent_state.tasks:
                for task in agent_state.tasks:
                    if hasattr(task, 'interrupts') and task.interrupts:
                        logger.info(f"  - Found {len(task.interrupts)} interrupt(s) in task '{task.name}'")
                        interrupts.extend(task.interrupts)
            
            if not interrupts:
                logger.debug("No interrupts found, continuing without approval")
                return
            
            logger.info(f"Processing {len(interrupts)} interrupt(s)")
            
            # Process each interrupt
            for interrupt_obj in interrupts:
                approval_payload = interrupt_obj.value
                
                logger.info(f"Processing interrupt payload for tool: {approval_payload.get('tool_name')}")
                
                logger.info("Processing interrupt approval request", extra={
                    "event_type": "approval_request_from_interrupt",
                    "thread_id": thread_id,
                    "payload_type": approval_payload.get("approval_type", "single")
                })
                
                # Check if it's a batch approval or single approval
                if approval_payload.get("approval_type") == "batch":
                    # Batch approval request
                    yield StreamEventFactory.batch_approval_request(
                        tool_calls=approval_payload.get("tool_calls", []),
                        options=approval_payload.get("options", [])
                    )
                else:
                    # Single approval request with rich context
                    # Convert enum values to strings for JSON serialization
                    risk_level = approval_payload.get("risk_level", "moderate")
                    if hasattr(risk_level, 'value'):
                        risk_level = risk_level.value
                    
                    default_approval_level = approval_payload.get("default_approval_level", "once")
                    if hasattr(default_approval_level, 'value'):
                        default_approval_level = default_approval_level.value
                    
                    available_levels = approval_payload.get("available_approval_levels", ["once"])
                    available_levels = [
                        level.value if hasattr(level, 'value') else level
                        for level in available_levels
                    ]
                    
                    yield StreamEventFactory.approval_request(
                        tool_name=approval_payload.get("tool_name"),
                        tool_call_id=approval_payload.get("tool_call_id"),
                        tool_input=approval_payload.get("tool_input", {}),
                        message=approval_payload.get("message", "Approval required"),
                        # Enhanced fields from ApprovalContext
                        risk_level=risk_level,
                        affected_resources=approval_payload.get("affected_resources", []),
                        reversible=approval_payload.get("reversible", True),
                        estimated_impact=approval_payload.get("estimated_impact", ""),
                        similar_operations_count=approval_payload.get("similar_operations_count", 0),
                        available_approval_levels=available_levels,
                        default_approval_level=default_approval_level
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
