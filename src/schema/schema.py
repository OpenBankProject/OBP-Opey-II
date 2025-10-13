from concurrent.futures import thread
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolCall,
    ToolMessage,
    message_to_dict,
    messages_from_dict,
)
from pydantic import BaseModel, Field

import json

def convert_message_content_to_string(content: str | list[str | dict]) -> str:
    if isinstance(content, str):
        return content
    text: list[str] = []
    for content_item in content:
        if isinstance(content_item, str):
            text.append(content_item)
            continue
        if content_item["type"] == "text":
            text.append(content_item["text"])
    return "".join(text)

def convert_message_content_to_dict(content: str | list[str | dict]) -> dict[str, Any] | str:
    try:
        content = json.loads(content)
        return content
    except json.JSONDecodeError as e:
        print(f"Failed to parse content {e.doc}\n\n with error {e.msg}")
        return convert_message_content_to_string(content)

class AgentResponse(BaseModel):
    """Response from the agent when called via /invoke."""

    message: dict[str, Any] = Field(
        description="Final response from the agent, as a serialized LangChain message.",
        examples=[
            {
                "message": {
                    "type": "ai",
                    "data": {"content": "The weather in Tokyo is 70 degrees.", "type": "ai"},
                }
            }
        ],
    )


class ChatMessage(BaseModel):
    """Message in a chat."""

    type: Literal["human", "ai", "tool"] = Field(
        description="Role of the message.",
        examples=["human", "ai", "tool"],
    )
    content: str | dict = Field(
        description="Content of the message.",
        examples=["Hello, world!"],
    )
    tool_calls: list[ToolCall] = Field(
        description="Tool calls in the message.",
        default=[],
    )
    tool_approval_request: bool = Field(
        description="Whether this message is an approval request for a tool call.",
        default=False,
    )
    tool_call_id: str | None = Field(
        description="Tool call that this message is responding to.",
        default=None,
        examples=["call_Jja7J89XsjrOLA5r!MEOW!SL"],
    )
    tool_status: str | None = Field(
        description="Tool status of the message.",
        default=None,
        examples=["success", "error"],
    )
    run_id: str | None = Field(
        description="Run ID of the message.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    original: dict[str, Any] = Field(
        description="Original LangChain message in serialized form.",
        default={},
    )

    @classmethod
    def from_langchain(cls, message: BaseMessage) -> "ChatMessage":
        """Create a ChatMessage from a LangChain message."""
        original = message_to_dict(message)
        match message:
            case HumanMessage():
                human_message = cls(
                    type="human",
                    content=convert_message_content_to_string(message.content),
                    original=original,
                )
                return human_message
            case AIMessage():
                ai_message = cls(
                    type="ai",
                    content=convert_message_content_to_string(message.content),
                    original=original,
                )
                if message.tool_calls:
                    ai_message.tool_calls = message.tool_calls
                return ai_message
            case ToolMessage():
                tool_status = original["data"].get("status")
                if tool_status is None:
                    print(
                        f"Tool status is None for message {message}, falling back to success."
                    )
                    tool_status = "success"
                tool_message = cls(
                    type="tool",
                    content=convert_message_content_to_dict(message.content), # we need a smarter way to process content from tool messages, i.e. if it is a valid dict, leave it as so, otherwise convert to string
                    tool_call_id=message.tool_call_id,
                    original=original,
                    tool_status=tool_status,
                )
                return tool_message
            case _:
                raise ValueError(f"Unsupported message type: {message.__class__.__name__}")

    def to_langchain(self) -> BaseMessage:
        """Convert the ChatMessage to a LangChain message."""
        if self.original:
            raw_original = messages_from_dict([self.original])[0]
            raw_original.content = self.content
            return raw_original
        match self.type:
            case "human":
                return HumanMessage(content=self.content)
            case "ai":
                ai_msg = AIMessage(content=self.content)
                if self.tool_calls:
                    ai_msg.tool_calls = self.tool_calls
                return ai_msg
            case _:
                raise NotImplementedError(f"Unsupported message type: {self.type}")

    def pretty_print(self) -> None:
        """Pretty print the ChatMessage."""
        lc_msg = self.to_langchain()
        lc_msg.pretty_print()


class Feedback(BaseModel):
    """Feedback for a run, to record to LangSmith."""

    run_id: str = Field(
        description="Run ID to record feedback for.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    key: str = Field(
        description="Feedback key.",
        examples=["human-feedback-stars"],
    )
    score: float = Field(
        description="Feedback score.",
        examples=[0.8],
    )
    kwargs: dict[str, Any] = Field(
        description="Additional feedback kwargs, passed to LangSmith.",
        default={},
        examples=[{"comment": "In-line human feedback"}],
    )


class FeedbackResponse(BaseModel):
    status: Literal["success"] = "success"

class ToolCallApproval(BaseModel):
    approval: Literal["approve", "deny"] = Field(
        description="Approval status for the tool call.",
    )
    level: Literal["once", "session", "user"] = Field(
        description="Level of approval.",
    )
    tool_call_id: str = Field(
        description="Tool call ID to approve or deny.",
        examples=["call_Jja7J89XsjrOLA5r!MEOW!SL"],
    )

class UserInput(BaseModel):
    """Basic user input for the agent."""

    message: str = Field(
        description="User input to the agent.",
        examples=["What is the weather in Tokyo?"],
    )
    thread_id: str | None = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    tool_call_approval: ToolCallApproval = Field(
        description="Whether this input is a tool call approval.",
        default=False,
    )


class StreamInput(UserInput):
    """User input for streaming the agent's response."""

    stream_tokens: bool = Field(
        description="Whether to stream LLM tokens to the client.",
        default=True,
    )

class ConsentAuthBody(BaseModel):
    consent_id: str = Field(
        description="OBP Consent ID to authorize."
    )
    consent_challenge_answer: str = Field(
        description="Answer to the consent challenge."
    )

class AuthResponse(BaseModel):
    success: bool = Field(
        description="Whether Auth was successful or not"
    )

class SessionCreateResponse(BaseModel):
    message: str = Field(
        description="Message about session creation"
    )
    session_type: Literal["authenticated", "anonymous"] = Field(
        description="Type of session created"
    )
    usage_limits: dict[str, Any] = Field(
        description="Usage limits for the session (for anonymous sessions)",
        default={}
    )

class UsageInfoResponse(BaseModel):
    session_type: Literal["authenticated", "anonymous"] = Field(
        description="Type of session"
    )
    unlimited_usage: bool = Field(
        description="Whether the session has unlimited usage",
        default=False
    )
    tokens_used: int = Field(
        description="Number of tokens used",
        default=0
    )
    token_limit: int = Field(
        description="Maximum tokens allowed",
        default=0
    )
    tokens_remaining: int = Field(
        description="Number of tokens remaining",
        default=0
    )
    requests_made: int = Field(
        description="Number of requests made",
        default=0
    )
    request_limit: int = Field(
        description="Maximum requests allowed",
        default=0
    )
    requests_remaining: int = Field(
        description="Number of requests remaining",
        default=0
    )
    approaching_token_limit: bool = Field(
        description="Whether approaching token limit (80%)",
        default=False
    )
    approaching_request_limit: bool = Field(
        description="Whether approaching request limit (80%)",
        default=False
    )

class SessionUpgradeResponse(BaseModel):
    message: str = Field(
        description="Message about session upgrade"
    )
    session_type: Literal["authenticated"] = Field(
        description="Type of session after upgrade"
    )
    previous_usage: dict[str, int] = Field(
        description="Previous usage statistics before upgrade"
    )
