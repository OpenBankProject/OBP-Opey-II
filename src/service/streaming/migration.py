import uuid
from typing import Dict, Any, Union
from langchain_core.messages import BaseMessage

from .events import StreamEvent, StreamEventFactory
from schema import ChatMessage


class StreamEventMigrator:
    """
    Utility to convert between old and new streaming event formats for backward compatibility
    """

    @staticmethod
    def new_to_old_format(event: StreamEvent) -> Dict[str, Any]:
        """
        Convert new StreamEvent to old format for clients that haven't been updated

        Args:
            event: New StreamEvent instance

        Returns:
            Dict in old format compatible with legacy clients
        """

        match event.type:
            case "assistant_start":
                # Old format didn't have explicit start events
                return {"type": "keep_alive"}

            case "assistant_token":
                return {
                    "type": "token",
                    "content": event.content
                }

            case "assistant_complete":
                # Convert to old message format
                chat_message = ChatMessage(
                    type="ai",
                    content=event.content,
                    tool_calls=event.tool_calls or [],
                    run_id=None
                )
                return {
                    "type": "message",
                    "content": chat_message.model_dump()
                }

            case "tool_start":
                # Old format didn't have explicit tool start events
                return {"type": "keep_alive"}

            case "tool_token":
                # Old format didn't stream tool tokens
                return {"type": "keep_alive"}

            case "tool_end":
                # Convert to old tool message format
                chat_message = ChatMessage(
                    type="tool",
                    content=event.tool_output,
                    tool_call_id=event.tool_call_id,
                    tool_status=event.status,
                    run_id=None
                )
                return {
                    "type": "tool",
                    "content": chat_message.model_dump()
                }

            case "error":
                return {
                    "type": "error",
                    "content": event.error_message
                }

            case "approval_request":
                return {
                    "type": "approval_request",
                    "tool_name": event.tool_name,
                    "tool_call_id": event.tool_call_id,
                    "tool_input": event.tool_input,
                    "message": event.message
                }

            case "keep_alive":
                return {"type": "keep_alive"}

            case "stream_end":
                return {"type": "done"}

            case _:
                # Fallback for unknown event types
                return {"type": "keep_alive"}

    @staticmethod
    def old_to_new_format(old_event: Dict[str, Any]) -> Union[StreamEvent, None]:
        """
        Convert old format event to new StreamEvent for processing

        Args:
            old_event: Dict in old format

        Returns:
            StreamEvent instance or None if not convertible
        """

        event_type = old_event.get("type")

        match event_type:
            case "token":
                return StreamEventFactory.assistant_token(
                    content=old_event["content"],
                    message_id=old_event.get("run_id", str(uuid.uuid4()))
                )

            case "message":
                content_data = old_event["content"]
                if isinstance(content_data, dict):
                    msg_type = content_data.get("type", "ai")

                    if msg_type == "ai":
                        return StreamEventFactory.assistant_complete(
                            content=content_data.get("content", ""),
                            message_id=old_event.get("run_id", str(uuid.uuid4())),
                            tool_calls=content_data.get("tool_calls", [])
                        )
                    elif msg_type == "tool":
                        return StreamEventFactory.tool_end(
                            tool_name="unknown",  # Not available in old format
                            tool_call_id=content_data.get("tool_call_id", ""),
                            tool_output=content_data.get("content"),
                            status=content_data.get("tool_status", "success")
                        )

            case "error":
                return StreamEventFactory.error(
                    error_message=old_event["content"]
                )

            case "approval_request":
                return StreamEventFactory.approval_request(
                    tool_name=old_event.get("tool_name", "unknown"),
                    tool_call_id=old_event.get("tool_call_id", ""),
                    tool_input=old_event.get("tool_input", {}),
                    message=old_event.get("message", "Approval required")
                )

            case "keep_alive":
                return StreamEventFactory.keep_alive()

            case _:
                return None

    @staticmethod
    def to_sse_legacy(event: StreamEvent) -> str:
        """
        Convert StreamEvent to legacy SSE format

        Args:
            event: StreamEvent to convert

        Returns:
            SSE formatted string in legacy format
        """

        old_format = StreamEventMigrator.new_to_old_format(event)

        if old_format.get("type") == "done":
            return "data: [DONE]\n\n"
        else:
            import json
            return f"data: {json.dumps(old_format)}\n\n"

    @staticmethod
    def extract_run_id_from_langchain_message(message: BaseMessage) -> str:
        """
        Extract run_id from LangChain message metadata if available

        Args:
            message: LangChain message

        Returns:
            Run ID string or empty string if not found
        """

        if hasattr(message, 'additional_kwargs'):
            return message.additional_kwargs.get('run_id', '')

        return ''

    @staticmethod
    def should_use_legacy_format(user_agent: str = None, client_version: str = None) -> bool:
        """
        Determine if legacy format should be used based on client information

        Args:
            user_agent: HTTP User-Agent header
            client_version: Client version if available

        Returns:
            True if legacy format should be used
        """

        # For now, default to new format unless specifically requested
        # In the future, you could check user_agent or client_version
        # to determine compatibility

        if client_version:
            # Example: use legacy for versions < 2.0.0
            try:
                major_version = int(client_version.split('.')[0])
                return major_version < 2
            except (ValueError, IndexError):
                pass

        # Default to new format
        return False


class BackwardCompatibilityWrapper:
    """
    Wrapper that can emit events in both old and new formats for transition period
    """

    def __init__(self, use_legacy: bool = False):
        self.use_legacy = use_legacy
        self.migrator = StreamEventMigrator()

    def format_event(self, event: StreamEvent) -> str:
        """
        Format event according to configured format

        Args:
            event: StreamEvent to format

        Returns:
            SSE formatted string
        """

        if self.use_legacy:
            return self.migrator.to_sse_legacy(event)
        else:
            return event.to_sse_data()

    def set_legacy_mode(self, use_legacy: bool):
        """Enable or disable legacy mode"""
        self.use_legacy = use_legacy


# Convenience functions for common migration scenarios
def convert_old_stream_to_new(old_events: list) -> list:
    """Convert a list of old format events to new format"""
    migrator = StreamEventMigrator()
    new_events = []

    for old_event in old_events:
        new_event = migrator.old_to_new_format(old_event)
        if new_event:
            new_events.append(new_event)

    return new_events


def convert_new_stream_to_old(new_events: list) -> list:
    """Convert a list of new format events to old format"""
    migrator = StreamEventMigrator()
    old_events = []

    for new_event in new_events:
        old_event = migrator.new_to_old_format(new_event)
        old_events.append(old_event)

    return old_events
