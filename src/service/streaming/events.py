from typing import Any, Dict, Literal, Union, Optional
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod


class BaseStreamEvent(BaseModel, ABC):
    """Base class for all stream events"""
    type: str
    timestamp: Optional[float] = None

    @abstractmethod
    def to_sse_data(self) -> str:
        """Convert event to SSE data format"""
        pass


class AssistantStartEvent(BaseStreamEvent):
    """Event fired when the assistant starts responding"""
    type: Literal["assistant_start"] = "assistant_start"

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class AssistantTokenEvent(BaseStreamEvent):
    """Event fired for each token from the assistant"""
    type: Literal["assistant_token"] = "assistant_token"
    content: str = Field(description="The token content")

    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


class AssistantEndEvent(BaseStreamEvent):
    """Event fired when the assistant finishes responding"""
    type: Literal["assistant_end"] = "assistant_end"
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


class ToolEndEvent(BaseStreamEvent):
    """Event fired when a tool execution completes"""
    type: Literal["tool_end"] = "tool_end"
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
    AssistantEndEvent,
    ToolStartEvent,
    ToolTokenEvent,
    ToolEndEvent,
    ErrorEvent,
    KeepAliveEvent,
    ApprovalRequestEvent,
    StreamEndEvent
]


class StreamEventFactory:
    """Factory class for creating stream events"""

    @staticmethod
    def assistant_start() -> AssistantStartEvent:
        return AssistantStartEvent()

    @staticmethod
    def assistant_token(content: str) -> AssistantTokenEvent:
        return AssistantTokenEvent(content=content)

    @staticmethod
    def assistant_end(content: str, tool_calls: Optional[list] = None) -> AssistantEndEvent:
        return AssistantEndEvent(content=content, tool_calls=tool_calls or [])

    @staticmethod
    def tool_start(tool_name: str, tool_call_id: str, tool_input: Dict[str, Any]) -> ToolStartEvent:
        return ToolStartEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input
        )

    @staticmethod
    def tool_token(tool_call_id: str, content: str) -> ToolTokenEvent:
        return ToolTokenEvent(tool_call_id=tool_call_id, content=content)

    @staticmethod
    def tool_end(
        tool_name: str,
        tool_call_id: str,
        tool_output: Any,
        status: Literal["success", "error"] = "success"
    ) -> ToolEndEvent:
        return ToolEndEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_output=tool_output,
            status=status
        )

    @staticmethod
    def error(
        error_message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> ErrorEvent:
        return ErrorEvent(
            error_message=error_message,
            error_code=error_code,
            details=details
        )

    @staticmethod
    def keep_alive() -> KeepAliveEvent:
        return KeepAliveEvent()

    @staticmethod
    def approval_request(
        tool_name: str,
        tool_call_id: str,
        tool_input: Dict[str, Any],
        message: str
    ) -> ApprovalRequestEvent:
        return ApprovalRequestEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            message=message
        )

    @staticmethod
    def stream_end() -> StreamEndEvent:
        return StreamEndEvent()
