from langgraph.graph import MessagesState
from pprint import pprint
from typing import Annotated, Dict, List, Optional, Tuple
from datetime import datetime
import operator


def merge_dicts(left: dict, right: dict) -> dict:
    """Merge two dictionaries, with right taking precedence."""
    return {**left, **right}


def make_approval_key(tool_name: str, operation: str) -> str:
    """
    Create a serializable approval key from tool name and operation.
    Uses string format instead of tuple to avoid JSON serialization issues.
    """
    return f"{tool_name}:{operation}"


def parse_approval_key(key: str) -> Tuple[str, str]:
    """Parse an approval key back into (tool_name, operation) tuple."""
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid approval key format: {key}")
    return parts[0], parts[1]


### States
class OpeyGraphState(MessagesState):
    """
    Enhanced state for Opey agent with approval tracking.
    """
    conversation_summary: str
    current_state: str
    aggregated_context: str
    total_tokens: int
    
    # Approval tracking (session-level)
    # Key: "tool_name:operation" -> Value: approved/denied
    # Using string keys instead of tuples for JSON serialization compatibility
    session_approvals: Annotated[Dict[str, bool], merge_dicts]
    
    # Timestamps for approvals to check expiration
    # Key: "tool_name:operation" -> Value: timestamp
    approval_timestamps: Annotated[Dict[str, datetime], merge_dicts]