import json
import uuid
import logging
from typing import AsyncGenerator, Optional, Dict, Any
from langchain_core.runnables.schema import StreamEvent as LangGraphStreamEvent
from langchain_core.messages import AIMessage, ToolMessage

from .events import StreamEvent, StreamEventFactory
from schema import StreamInput, convert_message_content_to_string

logger = logging.getLogger(__name__)


class BaseEventProcessor:
    """Base class for event processors"""

    def __init__(self, stream_input: StreamInput):
        self.stream_input = stream_input
        self.state = {}

    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process a LangGraph event and yield stream events"""
        yield  # Make this an async generator


class AssistantEventProcessor(BaseEventProcessor):
    """Processes events related to assistant responses"""

    def __init__(self, stream_input: StreamInput):
        super().__init__(stream_input)
        self.assistant_started = False
        self.streaming_content = ""
        self.current_tool_calls = []
        self.current_message_id = None
        self.run_id = None

    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process assistant-related events"""

        # Handle AI message completion (assistant_complete)
        if (
            event["event"] == "on_chain_end"
            and any(t.startswith("graph:step:") for t in event.get("tags", []))
            and event["data"].get("output") is not None
            and "messages" in event["data"]["output"]
            and event["metadata"].get("langgraph_node", "") == "opey"
        ):
            messages = event["data"]["output"]["messages"]
            if not isinstance(messages, list):
                messages = [messages]

            for message in messages:
                if isinstance(message, AIMessage):
                    try:
                        content = convert_message_content_to_string(message.content)
                        tool_calls = getattr(message, 'tool_calls', [])

                        # Extract message ID, fallback to generating one if not available
                        message_id = getattr(message, 'id', None) or str(uuid.uuid4())
                        run_id = self.run_id or event.get("run_id", None)

                        yield StreamEventFactory.assistant_complete(
                            content=content,
                            message_id=message_id,
                            run_id=run_id,
                            tool_calls=tool_calls
                        )
                    except Exception as e:
                        error_msg = f"Error processing assistant message completion: {str(e)}"
                        logger.error(error_msg, exc_info=True, extra={
                            "event_type": "assistant_complete_error",
                            "message_id": getattr(message, 'id', None),
                            "event_metadata": event.get("metadata", {})
                        })
                        yield StreamEventFactory.error(
                            error_message=error_msg,
                            error_code="assistant_processing_error",
                            for_message_id=getattr(message, 'id', None),
                            details={"original_event": event}
                        )

        # Handle streaming tokens (assistant_token)
        if (
            event["event"] == "on_chat_model_stream"
            and self.stream_input.stream_tokens
            and self._should_stream_tokens(event)
        ):
            try:
                content = event["data"]["chunk"].content
                if content:
                    # Initialize message ID for streaming if not already set
                    if not self.current_message_id:
                        # Try to get message ID from the chunk if available, otherwise generate one
                        chunk = event["data"]["chunk"]
                        self.current_message_id = getattr(chunk, 'id', None) or str(uuid.uuid4())

                    # Send assistant_start if this is the first token
                    if not self.assistant_started:
                        self.assistant_started = True
                        if not self.run_id:
                            grabbed_run_id = event.get("run_id", None)
                            self.run_id = grabbed_run_id
                        yield StreamEventFactory.assistant_start(message_id=self.current_message_id, run_id=self.run_id)

                    token_content = convert_message_content_to_string(content)
                    if token_content:
                        yield StreamEventFactory.assistant_token(
                            content=token_content,
                            message_id=self.current_message_id
                        )
            except Exception as e:
                error_msg = f"Error processing assistant token stream: {str(e)}"
                logger.error(error_msg, exc_info=True, extra={
                    "event_type": "assistant_token_error",
                    "message_id": self.current_message_id,
                    "event_metadata": event.get("metadata", {})
                })
                yield StreamEventFactory.error(
                    error_message=error_msg,
                    error_code="assistant_streaming_error",
                    for_message_id=self.current_message_id,
                    details={"original_event": event}
                )

    def _should_stream_tokens(self, event: LangGraphStreamEvent) -> bool:
        """Determine if tokens should be streamed for this event"""
        excluded_nodes = [
            "grade_documents",
            "transform_query",
            "retrieval_decider",
            "summarize_conversation"
        ]

        node_name = event["metadata"].get("langgraph_node", "")
        return node_name not in excluded_nodes

    def reset_for_new_message(self):
        """Reset state for a new message"""
        self.assistant_started = False
        self.streaming_content = ""
        self.current_tool_calls = []
        self.current_message_id = None
        self.run_id = None


class ToolEventProcessor(BaseEventProcessor):
    """Processes events related to tool execution"""

    def __init__(self, stream_input: StreamInput):
        super().__init__(stream_input)
        self.pending_tool_calls = {}

    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process tool-related events"""

        # Handle tool call initiation (tool_start)
        if (
            event["event"] == "on_chain_end"
            and any(t.startswith("graph:step:") for t in event.get("tags", []))
            and event["data"].get("output") is not None
            and "messages" in event["data"]["output"]
            and event["metadata"].get("langgraph_node", "") == "opey"
        ):
            messages = event["data"]["output"]["messages"]
            if not isinstance(messages, list):
                messages = [messages]


            grabbed_run_id = event.get("run_id", None)
            print(f"Grabbed run_id from tool: {grabbed_run_id}")  # Debugging line

            for message in messages:
                if isinstance(message, AIMessage) and hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        try:
                            self.pending_tool_calls[tool_call["id"]] = {
                                "name": tool_call["name"],
                                "input": tool_call["args"]
                            }

                            yield StreamEventFactory.tool_start(
                                tool_name=tool_call["name"],
                                tool_call_id=tool_call["id"],
                                tool_input=tool_call["args"]
                            )
                        except Exception as e:
                            error_msg = f"Error processing tool start: {str(e)}"
                            logger.error(error_msg, exc_info=True, extra={
                                "event_type": "tool_start_error",
                                "tool_call_id": tool_call.get("id"),
                                "tool_name": tool_call.get("name"),
                                "message_id": getattr(message, 'id', None),
                                "event_metadata": event.get("metadata", {})
                            })
                            yield StreamEventFactory.error(
                                error_message=error_msg,
                                error_code="tool_start_error",
                                for_message_id=getattr(message, 'id', None),
                                details={"tool_call": tool_call, "original_event": event}
                            )

        # Handle tool completion (tool_end)
        if (
            event["event"] == "on_chain_end"
            and any(t.startswith("graph:step:") for t in event.get("tags", []))
            and event["data"].get("output") is not None
            and "messages" in event["data"]["output"]
            and event["metadata"].get("langgraph_node", "") == "tools"
        ):
            messages = event["data"]["output"]["messages"]
            if not isinstance(messages, list):
                messages = [messages]

            grabbed_run_id = event.get("run_id", None)
            print(f"Grabbed run_id from tool completion: {grabbed_run_id}") 

            for message in messages:
                if isinstance(message, ToolMessage):
                    tool_call_id = message.tool_call_id
                    if tool_call_id in self.pending_tool_calls:
                        try:
                            tool_info = self.pending_tool_calls[tool_call_id]

                            # Log the message for debugging
                            logger.debug(f"Processing tool message: tool_call_id={tool_call_id}")
                            logger.debug(f"Message content: {str(message.content)[:500]}...")
                            logger.debug(f"Message type: {type(message.content)}")
                            logger.debug(f"Has status attr: {hasattr(message, 'status')}")
                            if hasattr(message, 'status'):
                                logger.debug(f"Status value: {message.status}")

                            # Determine status from message
                            status = "success"
                            if hasattr(message, 'status') and message.status == "error":
                                status = "error"
                                logger.error(f"TOOL_ERROR_DEBUG - Status set to error from message.status")
                            # elif isinstance(message.content, str):
                            #     content_lower = message.content.lower()
                            #     # Enhanced error detection patterns
                            #     # TODO: Change this it is absolutely horrible
                            #     error_patterns = [
                            #         'error:', 'exception(', 'failed', 'obp-', 'http 4', 'http 5',
                            #         'value too long', 'unauthorized', 'forbidden', 'bad request',
                            #         'internal server error', 'not found', 'conflict', 'unprocessable',
                            #         'obp api error', 'status: 4', 'status: 5'
                            #     ]
                            #     matched_patterns = [pattern for pattern in error_patterns if pattern in content_lower]
                            #     if matched_patterns:
                            #         status = "error"
                            #         logger.error(f"TOOL_ERROR_DEBUG - Status set to error from content patterns: {matched_patterns}")
                            #     else:
                            #         logger.error(f"TOOL_ERROR_DEBUG - No error patterns matched in content")

                            logger.error(f"TOOL_ERROR_DEBUG - Final status determination: {status}")

                            # Try to parse tool output
                            try:
                                tool_output = json.loads(message.content) if isinstance(message.content, str) else message.content
                            except (json.JSONDecodeError, TypeError):
                                tool_output = message.content

                            # Log tool completion for monitoring
                            if status == "error":
                                logger.error(f"Tool execution failed: {tool_output}", extra={
                                    "event_type": "tool_execution_failed",
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_info["name"],
                                    "tool_output": tool_output
                                })

                                # TODO: this also needs to be changed, create a converter function for langgraph to frontend errors
                                # Format error message for user display
                                if isinstance(tool_output, str) and "OBP API error" in tool_output:
                                    # Extract the actual error message from the exception string
                                    if "): " in tool_output:
                                        actual_error = tool_output.split("): ", 1)[1]
                                    else:
                                        actual_error = tool_output
                                    user_error_msg = f"API Error: {actual_error}"
                                else:
                                    user_error_msg = f"Tool '{tool_info['name']}' failed: {tool_output}"

                                logger.error(f"TOOL_ERROR_STREAM - Emitting error event for tool_call_id={tool_call_id}")
                                # Emit error event for immediate visibility
                                error_event = StreamEventFactory.error(
                                    error_message=user_error_msg,
                                    error_code="tool_execution_error",
                                    for_message_id=getattr(message, 'id', None),
                                    details={"tool_call_id": tool_call_id, "tool_name": tool_info["name"], "tool_output": tool_output}
                                )
                                logger.error(f"TOOL_ERROR_STREAM - About to yield error event: {error_event.model_dump_json()}")
                                yield error_event
                                logger.error(f"TOOL_ERROR_STREAM - Successfully yielded error event")

                            logger.error(f"TOOL_END_STREAM - About to emit tool_end event for tool_call_id={tool_call_id} with status={status}")
                            logger.info(f"TOOL_END_STREAM - About to emit tool_end event for tool_call_id={tool_call_id} with status={status}")
                            tool_end_event = StreamEventFactory.tool_end(
                                tool_name=tool_info["name"],
                                tool_call_id=tool_call_id,
                                tool_output=tool_output,
                                status=status
                            )
                            logger.error(f"TOOL_END_STREAM - Yielding tool_end event: {tool_end_event.model_dump_json()}")
                            yield tool_end_event
                            logger.error(f"TOOL_END_STREAM - Successfully yielded tool_end event")

                            # Remove from pending
                            del self.pending_tool_calls[tool_call_id]
                        except Exception as e:
                            error_msg = f"Error processing tool completion: {str(e)}"
                            logger.error(error_msg, exc_info=True, extra={
                                "event_type": "tool_end_error",
                                "tool_call_id": tool_call_id,
                                "message_id": getattr(message, 'id', None),
                                "event_metadata": event.get("metadata", {})
                            })
                            yield StreamEventFactory.error(
                                error_message=error_msg,
                                error_code="tool_end_error",
                                for_message_id=getattr(message, 'id', None),
                                details={"tool_call_id": tool_call_id, "original_event": event}
                            )


class ApprovalEventProcessor(BaseEventProcessor):
    """Processes events related to human approval requests"""

    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process approval-related events"""

        # This will be handled separately in the main streaming logic
        # since approval requires special state management
        return
        yield  # Make this an async generator


class ErrorEventProcessor(BaseEventProcessor):
    """Processes error events"""

    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process error events"""

        # Handle various error conditions from LangGraph
        if event["event"] == "on_chain_error":
            error_data = event["data"]
            error_message = str(error_data.get("error", "An error occurred"))
            message_id = error_data.get("id")

            # Log the chain error
            logger.error(f"LangGraph chain error: {error_message}", extra={
                "event_type": "langgraph_chain_error",
                "message_id": message_id,
                "event_metadata": event.get("metadata", {}),
                "error_data": error_data
            })

            yield StreamEventFactory.error(
                error_message=error_message,
                error_code="chain_error",
                for_message_id=message_id,
                details={"event_metadata": event.get("metadata", {}), "error_data": error_data}
            )

        elif event["event"] == "on_tool_error":
            error_data = event["data"]
            error_message = f"Tool error: {error_data.get('error', 'Unknown tool error')}"
            tool_name = event.get("metadata", {}).get("tool_name")

            # Log the tool error
            logger.error(f"LangGraph tool error: {error_message}", extra={
                "event_type": "langgraph_tool_error",
                "tool_name": tool_name,
                "event_metadata": event.get("metadata", {}),
                "error_data": error_data
            })

            yield StreamEventFactory.error(
                error_message=error_message,
                error_code="tool_error",
                details={"tool_name": tool_name, "event_metadata": event.get("metadata", {}), "error_data": error_data}
            )


class StreamEventOrchestrator:
    """Orchestrates multiple event processors"""

    def __init__(self, stream_input: StreamInput):
        self.stream_input = stream_input

        # Initialize processors
        self.processors = [
            AssistantEventProcessor(stream_input),
            ToolEventProcessor(stream_input),
            ApprovalEventProcessor(stream_input),
            ErrorEventProcessor(stream_input)
        ]

    async def process_event(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process an event through all relevant processors"""

        try:
            # Let each processor handle the event
            for processor in self.processors:
                async for stream_event in processor.process(event):
                    yield stream_event

        except Exception as e:
            # Log the processor error
            error_msg = f"Error processing stream event: {str(e)}"
            logger.error(error_msg, exc_info=True, extra={
                "event_type": "stream_processor_error",
                "event_name": event.get("event"),
                "event_metadata": event.get("metadata", {}),
                "processor_count": len(self.processors)
            })

            # If any processor fails, emit an error event
            yield StreamEventFactory.error(
                error_message=error_msg,
                error_code="processing_error",
                details={"original_event": event, "processor_count": len(self.processors)}
            )

    def get_tool_processor(self) -> ToolEventProcessor:
        """Get the tool processor for special operations"""
        for processor in self.processors:
            if isinstance(processor, ToolEventProcessor):
                return processor
        raise RuntimeError("Tool processor not found")

    def get_assistant_processor(self) -> AssistantEventProcessor:
        """Get the assistant processor for special operations"""
        for processor in self.processors:
            if isinstance(processor, AssistantEventProcessor):
                return processor
        raise RuntimeError("Assistant processor not found")

    def reset_for_new_conversation(self):
        """Reset all processors for a new conversation"""
        for processor in self.processors:
            if hasattr(processor, 'reset_for_new_message'):
                processor.reset_for_new_message()
