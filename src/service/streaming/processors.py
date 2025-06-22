import json
from typing import AsyncGenerator, Optional, Dict, Any
from langchain_core.runnables.schema import StreamEvent as LangGraphStreamEvent
from langchain_core.messages import AIMessage, ToolMessage

from .events import StreamEvent, StreamEventFactory
from schema import StreamInput, convert_message_content_to_string


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

    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        """Process assistant-related events"""

        # Handle AI message completion (assistant_end)
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
                    content = convert_message_content_to_string(message.content)
                    tool_calls = getattr(message, 'tool_calls', [])

                    yield StreamEventFactory.assistant_end(
                        content=content,
                        tool_calls=tool_calls
                    )

        # Handle streaming tokens (assistant_token)
        if (
            event["event"] == "on_chat_model_stream"
            and self.stream_input.stream_tokens
            and self._should_stream_tokens(event)
        ):
            content = event["data"]["chunk"].content
            if content:
                # Send assistant_start if this is the first token
                if not self.assistant_started:
                    self.assistant_started = True
                    yield StreamEventFactory.assistant_start()

                token_content = convert_message_content_to_string(content)
                if token_content:
                    yield StreamEventFactory.assistant_token(
                        content=token_content
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

            for message in messages:
                if isinstance(message, AIMessage) and hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        self.pending_tool_calls[tool_call["id"]] = {
                            "name": tool_call["name"],
                            "input": tool_call["args"]
                        }

                        yield StreamEventFactory.tool_start(
                            tool_name=tool_call["name"],
                            tool_call_id=tool_call["id"],
                            tool_input=tool_call["args"]
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

            for message in messages:
                if isinstance(message, ToolMessage):
                    tool_call_id = message.tool_call_id
                    if tool_call_id in self.pending_tool_calls:
                        tool_info = self.pending_tool_calls[tool_call_id]

                        # Determine status from message
                        status = "success"
                        if hasattr(message, 'status') and message.status == "error":
                            status = "error"

                        # Try to parse tool output
                        try:
                            tool_output = json.loads(message.content) if isinstance(message.content, str) else message.content
                        except (json.JSONDecodeError, TypeError):
                            tool_output = message.content

                        yield StreamEventFactory.tool_end(
                            tool_name=tool_info["name"],
                            tool_call_id=tool_call_id,
                            tool_output=tool_output,
                            status=status
                        )

                        # Remove from pending
                        del self.pending_tool_calls[tool_call_id]


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
            yield StreamEventFactory.error(
                error_message=str(error_data.get("error", "An error occurred")),
                error_code="chain_error",
                details={"event_metadata": event["metadata"]}
            )

        elif event["event"] == "on_tool_error":
            error_data = event["data"]
            yield StreamEventFactory.error(
                error_message=f"Tool error: {error_data.get('error', 'Unknown tool error')}",
                error_code="tool_error",
                details={"tool_name": event["metadata"].get("tool_name"), "event_metadata": event["metadata"]}
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
            # If any processor fails, emit an error event
            yield StreamEventFactory.error(
                error_message=f"Error processing stream event: {str(e)}",
                error_code="processing_error",
                details={"original_event": event}
            )

    def get_tool_processor(self) -> ToolEventProcessor:
        """Get the tool processor for special operations"""
        for processor in self.processors:
            if isinstance(processor, ToolEventProcessor):
                return processor
        raise RuntimeError("Tool processor not found")
