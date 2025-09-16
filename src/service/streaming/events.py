from typing import Any, Dict, Literal, Union, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from abc import ABC, abstractmethod
import logging
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Setup logger
logger = logging.getLogger(__name__)


class BaseStreamEvent(BaseModel, ABC):
    """Base class for all stream events"""
    timestamp: Optional[float] = datetime.now().timestamp()

    @abstractmethod
    def to_sse_data(self) -> str:
        """Convert event to SSE data format"""
        pass


class AssistantStartEvent(BaseStreamEvent):
    """Event fired when the assistant starts responding"""
    type: Literal["assistant_start"] = "assistant_start"
    message_id: str
    run_id: str = Field(description="Unique identifier for this run")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class AssistantTokenEvent(BaseStreamEvent):
    """Event fired for each token from the assistant"""
    type: Literal["assistant_token"] = "assistant_token"
    message_id: str
    content: str = Field(description="The token content")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class AssistantCompleteEvent(BaseStreamEvent):
    """Event fired when the assistant finishes responding"""
    type: Literal["assistant_complete"] = "assistant_complete"
    message_id: str
    run_id: str = Field(description="Unique identifier for this run")
    content: str = Field(description="The complete response content")
    tool_calls: Optional[list] = Field(default=[], description="Any tool calls made by the assistant")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class ToolStartEvent(BaseStreamEvent):
    """Event fired when a tool execution starts"""
    type: Literal["tool_start"] = "tool_start"
    tool_name: str = Field(description="Name of the tool being executed")
    tool_call_id: str = Field(description="Unique identifier for this tool call")
    tool_input: Dict[str, Any] = Field(description="Input arguments to the tool")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class ToolTokenEvent(BaseStreamEvent):
    """Event fired for tokens during tool execution (if tool streams output)"""
    type: Literal["tool_token"] = "tool_token"
    tool_call_id: str = Field(description="Unique identifier for this tool call")
    content: str = Field(description="Token content from tool execution")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class ToolCompleteEvent(BaseStreamEvent):
    """Event fired when a tool execution completes"""
    type: Literal["tool_complete"] = "tool_complete"
    tool_name: str = Field(description="Name of the tool that was executed")
    tool_call_id: str = Field(description="Unique identifier for this tool call")
    tool_output: Any = Field(description="Output from the tool execution")
    status: Literal["success", "error"] = Field(description="Execution status")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class ErrorEvent(BaseStreamEvent):
    """Event fired when an error occurs"""
    type: Literal["error"] = "error"
    error_message: str = Field(description="Human readable error message")
    for_message_id: Optional[str] = Field(description="The message ID which the error is related to.")
    error_code: Optional[str] = Field(default=None, description="Machine readable error code")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error details")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class KeepAliveEvent(BaseStreamEvent):
    """Event fired to keep the connection alive"""
    type: Literal["keep_alive"] = "keep_alive"

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class ApprovalRequestEvent(BaseStreamEvent):
    """Event fired when human approval is required for a tool call"""
    type: Literal["approval_request"] = "approval_request"
    tool_name: str = Field(description="Name of the tool requiring approval")
    tool_call_id: str = Field(description="Unique identifier for this tool call")
    tool_input: Dict[str, Any] = Field(description="Input arguments to the tool")
    message: str = Field(description="Human readable message about what needs approval")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class StreamEndEvent(BaseStreamEvent):
    """Event fired when the stream ends"""
    type: Literal["stream_end"] = "stream_end"

    def to_sse_data(self) -> str:
        return "data: [DONE]\n\n"


# Union type for all possible stream events
StreamEvent = Union[
    AssistantStartEvent,
    AssistantTokenEvent,
    AssistantCompleteEvent,
    ToolStartEvent,
    ToolTokenEvent,
    ToolCompleteEvent,
    ErrorEvent,
    KeepAliveEvent,
    ApprovalRequestEvent,
    StreamEndEvent
]


class StreamEventFactory:
    """Factory class for creating stream events"""
    
    @staticmethod
    def _log_event(event: BaseStreamEvent, event_type: str, details: Dict[str, Any] = None, extra_messages: Dict[str, str] = None):
        """
        Pretty print and log an event in a single, well-formatted log entry
        
        Args:
            event: The event object to log
            event_type: The event type identifier (e.g., "ASSISTANT_START")
            details: Key details to display in the first log line
            extra_messages: Additional messages to log on separate lines
        """
        log_parts = []
        
        # Add header with event type and separator
        header = f"\n======== EVENT [{event_type}] ========"
        details_str = ", ".join([f"{k}={v}" for k, v in (details or {}).items()])
        log_parts.append(header)
        log_parts.append(details_str)
        
        # Add extra messages if any
        if extra_messages:
            log_parts.append("----- Additional Information -----")
            for key, message in extra_messages.items():
                log_parts.append(f"{key}: {message}")
        
        # Format and add the event data
        log_parts.append("----- Event Data -----")
        event_data = event.to_sse_data().strip()
        
        # Try to pretty print the JSON part of the event data
        try:
            # Extract just the JSON part from "data: {...}"
            json_part = event_data[6:] if event_data.startswith("data: ") else event_data
            if json_part != "[DONE]":  # Skip for stream_end events
                parsed_json = json.loads(json_part)
                formatted_json = json.dumps(parsed_json, indent=2)
                log_parts.append(f"data: {formatted_json}")
            else:
                log_parts.append(event_data)
        except:
            # Fall back to raw data if JSON parsing fails
            log_parts.append(event_data)
        
        # Add footer
        log_parts.append("=" * len(header))
        
        # Join all parts and log as a single message
        log_message = "\n".join(log_parts)
        logger.info(log_message)

    @staticmethod
    def assistant_start(message_id: str, run_id: str) -> AssistantStartEvent:
        event = AssistantStartEvent(message_id=message_id, run_id=run_id)
        StreamEventFactory._log_event(
            event, 
            "ASSISTANT_START", 
            {"message_id": message_id, "run_id": run_id}
        )
        return event

    @staticmethod
    def assistant_token(content: str, message_id: str) -> AssistantTokenEvent:
        event = AssistantTokenEvent(content=content, message_id=message_id)
        if os.getenv("LOG_TOKENS") == "true":
            # Only log token events if LOG_TOKENS env var is set to "true"  
            StreamEventFactory._log_event(
                event, 
                "ASSISTANT_TOKEN", 
                {"message_id": message_id, "content_length": len(content)}
            )
        return event

    @staticmethod
    def assistant_complete(content: str, message_id: str, run_id: str, tool_calls: Optional[list] = None) -> AssistantCompleteEvent:
        event = AssistantCompleteEvent(content=content, message_id=message_id, run_id=run_id, tool_calls=tool_calls or [])
        StreamEventFactory._log_event(
            event, 
            "ASSISTANT_COMPLETE", 
            {
                "message_id": message_id,
                "run_id": run_id,
                "content_length": len(content),
                "tool_calls": len(tool_calls or [])
            }
        )
        return event

    @staticmethod
    def tool_start(tool_name: str, tool_call_id: str, tool_input: Dict[str, Any]) -> ToolStartEvent:
        event = ToolStartEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input
        )
        StreamEventFactory._log_event(
            event, 
            "TOOL_START", 
            {"tool_name": tool_name, "tool_call_id": tool_call_id}
        )
        return event

    @staticmethod
    def tool_token(tool_call_id: str, content: str) -> ToolTokenEvent:
        event = ToolTokenEvent(tool_call_id=tool_call_id, content=content)
        StreamEventFactory._log_event(
            event, 
            "TOOL_TOKEN", 
            {"tool_call_id": tool_call_id, "content_length": len(content)}
        )
        return event

    @staticmethod
    def tool_end(
        tool_name: str,
        tool_call_id: str,
        tool_output: Any,
        status: Literal["success", "error"] = "success"
    ) -> ToolCompleteEvent:
        event = ToolCompleteEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_output=tool_output,
            status=status
        )
        StreamEventFactory._log_event(
            event, 
            "TOOL_COMPLETE", 
            {"tool_name": tool_name, "tool_call_id": tool_call_id, "status": status}
        )
        return event

    @staticmethod
    def error(
        error_message: str,
        error_code: Optional[str] = None,
        for_message_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> ErrorEvent:
        event = ErrorEvent(
            error_message=error_message,
            for_message_id=for_message_id,
            error_code=error_code,
            details=details
        )
        StreamEventFactory._log_event(
            event, 
            "ERROR", 
            {"error_code": error_code, "for_message_id": for_message_id},
            {"Error message": error_message}
        )
        return event

    @staticmethod
    def keep_alive() -> KeepAliveEvent:
        event = KeepAliveEvent()
        StreamEventFactory._log_event(
            event, 
            "KEEP_ALIVE", 
            {"message": "Sending keep-alive event"}
        )
        return event

    @staticmethod
    def approval_request(
        tool_name: str,
        tool_call_id: str,
        tool_input: Dict[str, Any],
        message: str
    ) -> ApprovalRequestEvent:
        event = ApprovalRequestEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            message=message
        )
        StreamEventFactory._log_event(
            event, 
            "APPROVAL_REQUEST", 
            {"tool_name": tool_name, "tool_call_id": tool_call_id},
            {"Approval message": message}
        )
        return event

    @staticmethod
    def stream_end() -> StreamEndEvent:
        event = StreamEndEvent()
        StreamEventFactory._log_event(
            event, 
            "STREAM_END", 
            {"message": "Stream completed"}
        )
        return event
