import os
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
_log_full = os.getenv("LOG_FULL_MESSAGES", "false").lower() == "true"


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

        # Emit thread_sync event first to ensure frontend has the correct thread_id
        # This is critical when the backend generates the thread_id (when not provided)
        yield StreamEventFactory.thread_sync(thread_id)

        orchestrator = orchestrator_repository.get_or_create(thread_id, stream_input)
        
        # Track if generator is being closed to avoid yielding in finally block
        generator_closing = False

        try:
            # Parse input for the graph
            if _log_full:
                logger.info(f"\n\nSTREAM INPUT: {stream_input.model_dump()}\n\n")
            else:
                msg_preview = (stream_input.message[:80] + "...") if stream_input.message and len(stream_input.message) > 80 else stream_input.message
                logger.info(f"Stream input: message={msg_preview!r} stream_tokens={stream_input.stream_tokens} has_approval={stream_input.tool_call_approval is not None}")
            if stream_input.tool_call_approval:
                approval = stream_input.tool_call_approval
                
                if approval.is_consent_response():
                    # Consent JWT response — resume consent_check_node interrupt
                    jwt_preview = approval.consent_jwt[:50] + "..." if approval.consent_jwt and len(approval.consent_jwt) > 50 else approval.consent_jwt
                    logger.info(f"🔐 CONSENT_FLOW: Received consent JWT from frontend (preview: {jwt_preview})", extra={
                        "event_type": "consent_jwt_processing",
                        "thread_id": thread_id,
                        "jwt_length": len(approval.consent_jwt) if approval.consent_jwt else 0,
                        "jwt_preview": jwt_preview,
                    })
                    
                    from langgraph.types import Command
                    graph_input = Command(
                        resume={"consent_jwt": approval.consent_jwt}
                    )
                    logger.info(f"🔐 CONSENT_FLOW: Created Command(resume={{consent_jwt: ...}}) to resume consent_check_node")
                
                elif approval.is_batch():
                    # Batch approval response
                    batch_decisions = approval.batch_decisions
                    if not batch_decisions:  # Type narrowing for linter
                        raise ValueError("Batch approval must have batch_decisions")
                    
                    logger.info(f"Processing batch approval", extra={
                        "event_type": "batch_approval_processing",
                        "thread_id": thread_id,
                        "decision_count": len(batch_decisions)
                    })
                    
                    # Convert to format expected by human_review_node
                    decisions = {}
                    for tool_call_id, decision in batch_decisions.items():
                        decisions[tool_call_id] = {
                            "approved": decision.approved,
                            "approval_level": decision.level
                        }
                    
                    from langgraph.types import Command
                    graph_input = Command(
                        resume={"decisions": decisions}
                    )
                
                elif approval.is_single():
                    # Single approval (backward compatible)
                    approved = approval.approval == "approve"
                    tool_call_id = approval.tool_call_id
                    approval_level = approval.level
                    
                    logger.info(f"Processing single approval: {tool_call_id}", extra={
                        "event_type": "single_approval_processing",
                        "thread_id": thread_id,
                        "approved": approved,
                        "approval_level": approval_level
                    })
                    
                    from langgraph.types import Command
                    graph_input = Command(
                        resume={
                            "approved": approved,
                            "approval_level": approval_level,
                            "tool_call_id": tool_call_id
                        }
                    )
                else:
                    error_msg = "ToolCallApproval must be either batch or single format"
                    logger.error(error_msg, extra={
                        "event_type": "invalid_approval_format",
                        "thread_id": thread_id
                    })
                    raise ValueError(error_msg)
                    
                logger.debug("Processing tool call approval", extra={
                    "event_type": "tool_approval_processing",
                    "thread_id": thread_id,
                    "is_batch": approval.is_batch()
                })
            else:
                # Regular user message
                input_message = ChatMessage(type="human", content=stream_input.message)

                # Resolve any pending consent/approval interrupts from a previous turn
                # that was cancelled without properly denying them. Without this, the
                # interrupted node may fire again and re-emit the same consent request.
                await self._fix_pending_interrupts(config)

                # CRITICAL: Check for orphaned tool calls before adding new message
                # This can happen when cancellation occurs during tool execution
                await self._fix_orphaned_tool_calls(config)
                
                graph_input = {"messages": [input_message.to_langchain()]}
                logger.debug("Processing user message", extra={
                    "event_type": "user_message_processing",
                    "thread_id": thread_id,
                    "message_type": input_message.type
                })
                
                # Note: user_message_confirmed event is emitted by UserMessageEventProcessor
                # after the message is added to the graph and assigned an ID

            # Stream events from the graph
            kwargs = {
                "input": graph_input,
                "config": config
            }

            event_count = 0
            last_event = None
            async for langgraph_event in self.graph.astream_events(**kwargs, version="v2"):
                event_count += 1
                
                try:
                    # Process each LangGraph event through our orchestrator
                    async for stream_event in orchestrator.process_event(langgraph_event):
                        yield stream_event
                except GeneratorExit:
                    # Generator being closed - stop processing and cleanup
                    logger.info(f"Stream generator closed during event processing", extra={
                        "event_type": "generator_closed",
                        "thread_id": thread_id,
                        "event_count": event_count
                    })
                    raise  # Re-raise to propagate closure
                except Exception as e:
                    error_msg = f"Error processing LangGraph event: {str(e)}"
                    logger.error(error_msg, exc_info=True, extra={
                        "event_type": "langgraph_event_processing_error",
                        "thread_id": thread_id,
                        "event_count": event_count,
                        "langgraph_event_type": langgraph_event.get("event"),
                        "langgraph_event_metadata": langgraph_event.get("metadata", {})
                    })
                    # Sanitize event data for serialization
                    safe_details = {
                        "event_count": event_count,
                        "event_type": langgraph_event.get("event"),
                        "error_type": type(e).__name__
                    }
                    yield StreamEventFactory.error(
                        error_message=error_msg,
                        error_code="langgraph_event_error",
                        details=safe_details
                    )

            logger.info(f"Processed {event_count} LangGraph events", extra={
                "event_type": "langgraph_events_completed",
                "thread_id": thread_id,
                "event_count": event_count
            })

            # After streaming completes, ALWAYS check the final state for interrupts
            # Even if this request was resuming from a previous interrupt, the graph
            # might have hit ANOTHER interrupt that needs to be handled
            # According to LangGraph docs, __interrupt__ appears in the state after stream ends
            logger.info("Stream completed, checking for interrupts...", extra={
                "event_type": "checking_interrupts",
                "thread_id": thread_id,
                "was_approval_response": bool(stream_input.tool_call_approval)
            })
            async for approval_event in self._handle_approval(config):
                yield approval_event

        except GeneratorExit:
            # Generator being closed - log and re-raise
            generator_closing = True
            logger.info(f"Stream response generator closed", extra={
                "event_type": "stream_generator_closed",
                "thread_id": thread_id
            })
            raise  # Re-raise to properly close the generator
        except Exception as e:
            error_msg = f"Streaming error: {str(e)}"
            logger.error(error_msg, exc_info=True, extra={
                "event_type": "stream_response_error",
                "thread_id": thread_id,
                "stream_tokens": stream_input.stream_tokens,
                "tool_approval": stream_input.tool_call_approval.model_dump() if stream_input.tool_call_approval else None,
            })
            # Sanitize error details to avoid serialization issues
            safe_details = {
                "thread_id": thread_id,
                "error_type": type(e).__name__
            }
            yield StreamEventFactory.error(
                error_message=error_msg,
                error_code="stream_error",
                details=safe_details
            )
        finally:
            # Only send stream end event if generator is not being forcefully closed
            if not generator_closing:
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

            task_count = len(agent_state.tasks) if agent_state.tasks else 0
            has_interrupt = '__interrupt__' in agent_state.values if agent_state.values else False

            if _log_full:
                logger.info(f"=== CHECKING FOR INTERRUPTS ===")
                logger.info(f"Agent state: next={agent_state.next}, tasks={task_count}, has_interrupt={has_interrupt}, keys={list(agent_state.values.keys()) if agent_state.values else 'None'}")

            # Collect all interrupts from tasks
            interrupts = []
            if agent_state.tasks:
                for task in agent_state.tasks:
                    if hasattr(task, 'interrupts') and task.interrupts:
                        interrupts.extend(task.interrupts)
            
            if not interrupts:
                logger.debug("No interrupts found in state after stream completed")
                return
            
            logger.info(f"Processing {len(interrupts)} interrupt(s)")
            
            # Process each interrupt
            for interrupt_obj in interrupts:
                approval_payload = interrupt_obj.value
                
                logger.info(f"Processing interrupt payload for tool: {approval_payload.get('tool_name')}")
                
                # Check if this is a consent interrupt (from consent_check_node)
                if approval_payload.get("consent_type") == "consent_required":
                    tool_call_count = approval_payload.get("tool_call_count", 1)
                    logger.info(
                        f"Processing consent request interrupt: operation={approval_payload.get('operation_id')} "
                        f"({tool_call_count} tool call(s))"
                    )
                    yield StreamEventFactory.consent_request(
                        tool_call_id=approval_payload.get("tool_call_id", ""),
                        tool_name=approval_payload.get("tool_name", ""),
                        operation_id=approval_payload.get("operation_id"),
                        required_roles=approval_payload.get("required_roles", []),
                        tool_call_count=tool_call_count,
                        bank_id=approval_payload.get("bank_id"),
                    )
                    continue
                
                logger.info("Processing interrupt approval request", extra={
                    "event_type": "approval_request_from_interrupt",
                    "thread_id": thread_id,
                    "payload_type": approval_payload.get("approval_type", "single")
                })
                
                # Extract tool_calls from payload (new unified format)
                tool_calls = approval_payload.get("tool_calls", [])
                available_scopes = approval_payload.get("available_scopes", ["once"])
                
                # Check if it's a batch approval or single approval
                if approval_payload.get("approval_type") == "batch" or len(tool_calls) > 1:
                    # Batch approval request
                    yield StreamEventFactory.batch_approval_request(
                        tool_calls=tool_calls,
                        options=available_scopes
                    )
                elif tool_calls:
                    # Single approval request - extract from first tool_call
                    tc = tool_calls[0]
                    
                    yield StreamEventFactory.approval_request(
                        tool_name=tc.get("tool_name"),
                        tool_call_id=tc.get("tool_call_id"),
                        tool_input=tc.get("tool_args", {}),
                        message=tc.get("description") or "Approval required",
                        risk_level="moderate",
                        affected_resources=[],
                        reversible=True,
                        estimated_impact="",
                        similar_operations_count=0,
                        available_approval_levels=available_scopes,
                        default_approval_level="once"
                    )
                else:
                    logger.warning("Interrupt payload has no tool_calls", extra={
                        "event_type": "empty_interrupt_payload",
                        "thread_id": thread_id,
                        "payload_keys": list(approval_payload.keys())
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
                details={"thread_id": thread_id, "error_type": type(e).__name__}
            )

    async def _fix_pending_interrupts(self, config: RunnableConfig) -> None:
        """
        Resolve any pending consent or approval interrupts before adding a new user message.

        When a user cancels a consent/approval dialog without properly denying it (i.e.
        without calling the /approval endpoint), the graph is left with:
          1. A pending interrupt task in the checkpoint, AND
          2. ToolMessages with consent_required / pending-approval content still in state

        If left unresolved, the interrupted node may re-run and emit the same interrupt
        again on the next turn. This method detects that situation and:
          - Replaces the stale consent_required ToolMessages with explicit denial messages
            (using the same IDs so the add_messages reducer updates them in-place)
          - Updates the checkpoint as if the interrupted node completed, which clears
            the pending interrupt task

        Safe to call even when there are no pending interrupts (no-op in that case).
        """
        from langchain_core.messages import ToolMessage as LCToolMessage

        thread_id = config.get("configurable", {}).get("thread_id")

        try:
            agent_state = await self.graph.aget_state(config)
            if not agent_state or not agent_state.tasks:
                return

            interrupts = []
            for task in agent_state.tasks:
                if hasattr(task, 'interrupts') and task.interrupts:
                    interrupts.extend(task.interrupts)

            if not interrupts:
                return

            logger.warning(
                f"Found {len(interrupts)} pending interrupt(s) for thread {thread_id} "
                f"before new user message — resolving as cancelled",
                extra={"event_type": "pending_interrupt_cleanup", "thread_id": thread_id}
            )

            messages = agent_state.values.get("messages", []) if agent_state.values else []

            for interrupt_obj in interrupts:
                payload = interrupt_obj.value

                if payload.get("consent_type") == "consent_required":
                    # Consent interrupt — replace consent_required ToolMessages with denials
                    tool_call_ids = payload.get("tool_call_ids", [])
                    if not tool_call_ids and payload.get("tool_call_id"):
                        tool_call_ids = [payload["tool_call_id"]]

                    denial_messages = []
                    for tool_call_id in tool_call_ids:
                        original_msg_id = None
                        for msg in messages:
                            if isinstance(msg, LCToolMessage) and msg.tool_call_id == tool_call_id:
                                original_msg_id = msg.id
                                break

                        denial_msg = LCToolMessage(
                            content="Consent request cancelled — user sent a new message.",
                            tool_call_id=tool_call_id,
                            status="error",
                        )
                        if original_msg_id:
                            denial_msg.id = original_msg_id  # Replace in-place via reducer
                        denial_messages.append(denial_msg)

                    # Update state as if consent_check completed with these denial messages,
                    # which clears the interrupt task in the checkpoint.
                    await self.graph.aupdate_state(
                        config,
                        {"messages": denial_messages},
                        as_node="consent_check",
                    )
                    logger.info(
                        f"Resolved pending consent interrupt for "
                        f"operation={payload.get('operation_id')} "
                        f"with {len(denial_messages)} denial(s)",
                        extra={"event_type": "consent_interrupt_resolved", "thread_id": thread_id}
                    )

                elif payload.get("tool_calls") or payload.get("tool_call_id"):
                    # Human-review (approval) interrupt — deny all pending tool calls
                    tool_calls = payload.get("tool_calls", [])
                    if not tool_calls and payload.get("tool_call_id"):
                        tool_calls = [{"tool_call_id": payload["tool_call_id"]}]

                    denial_messages = [
                        LCToolMessage(
                            content="Tool call cancelled — user sent a new message.",
                            tool_call_id=tc.get("tool_call_id"),
                            status="error",
                        )
                        for tc in tool_calls
                        if tc.get("tool_call_id")
                    ]

                    await self.graph.aupdate_state(
                        config,
                        {"messages": denial_messages},
                        as_node="human_review",
                    )
                    logger.info(
                        f"Resolved pending approval interrupt with {len(denial_messages)} denial(s)",
                        extra={"event_type": "approval_interrupt_resolved", "thread_id": thread_id}
                    )
                else:
                    logger.warning(
                        f"Unknown pending interrupt type for thread {thread_id}: {list(payload.keys())}",
                        extra={"event_type": "unknown_interrupt_type", "thread_id": thread_id}
                    )

        except Exception as e:
            logger.error(
                f"Error fixing pending interrupts: {e}",
                exc_info=True,
                extra={"event_type": "pending_interrupt_fix_error", "thread_id": thread_id}
            )

    async def _fix_orphaned_tool_calls(self, config: RunnableConfig) -> None:
        """
        Fix orphaned tool calls in the graph state.
        
        This can happen when cancellation occurs during tool execution:
        - AIMessage with tool_calls is in state
        - Tool was executing when user cancelled
        - ToolMessages may be missing or incomplete
        
        This method checks for such cases and adds dummy ToolMessages
        to satisfy LLM API requirements.
        """
        from langchain_core.messages import AIMessage, ToolMessage
        
        thread_id = config.get("configurable", {}).get("thread_id")
        
        try:
            # Get current graph state
            current_state = await self.graph.aget_state(config)
            if not current_state or not current_state.values:
                return
            
            messages = current_state.values.get("messages", [])
            if not messages:
                return
            
            # Find the last AIMessage with tool_calls
            last_ai_with_tools = None
            last_ai_index = -1
            
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    last_ai_with_tools = msg
                    last_ai_index = i
                    break
            
            if not last_ai_with_tools:
                return  # No tool calls to worry about
            
            # Find which tool calls already have ToolMessage results
            existing_tool_call_ids = set()
            for msg in messages[last_ai_index + 1:]:
                if isinstance(msg, ToolMessage):
                    existing_tool_call_ids.add(msg.tool_call_id)
            
            # Check for orphaned tool calls
            orphaned_tool_calls = []
            for tool_call in last_ai_with_tools.tool_calls:
                tool_call_id = tool_call.get("id")
                if tool_call_id and tool_call_id not in existing_tool_call_ids:
                    orphaned_tool_calls.append(tool_call)
            
            if not orphaned_tool_calls:
                return  # All tool calls have results
            
            # Create dummy ToolMessages for orphaned calls
            logger.warning(f"Found {len(orphaned_tool_calls)} orphaned tool calls in state for thread {thread_id}, adding dummy ToolMessages")
            
            dummy_messages = []
            for tool_call in orphaned_tool_calls:
                tool_call_id = tool_call.get("id")
                dummy_message = ToolMessage(
                    content="[Cancelled - tool execution was interrupted]",
                    tool_call_id=tool_call_id,
                    status="error"
                )
                dummy_messages.append(dummy_message)
                logger.info(f"Added dummy ToolMessage for orphaned tool_call_id: {tool_call_id}")
            
            # Update the graph state with dummy messages
            await self.graph.aupdate_state(config, {"messages": dummy_messages})
            logger.info(f"Successfully fixed {len(orphaned_tool_calls)} orphaned tool calls")
            
        except Exception as e:
            # Don't fail the request if this cleanup fails
            logger.error(f"Error fixing orphaned tool calls: {e}", exc_info=True, extra={
                "event_type": "orphaned_tool_call_fix_error",
                "thread_id": thread_id
            })

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
