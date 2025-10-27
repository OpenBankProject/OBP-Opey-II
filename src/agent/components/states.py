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
    
    Args:
        tool_name: Name of the tool (e.g., "obp_requests", "endpoint_retrieval_tool")
        operation: Operation identifier, which varies by tool:
            - For obp_requests: operationId (e.g., "OBPv4.0.0-getBank") or fallback to "METHOD:path"
            - For other tools: generic operation name or the tool name itself
    
    Returns:
        str: Approval key in format "tool_name:operation"
    """
    return f"{tool_name}:{operation}"


def parse_approval_key(key: str) -> Tuple[str, str]:
    """
    Parse an approval key back into (tool_name, operation) tuple.
    
    Args:
        key: Approval key in format "tool_name:operation"
        
    Returns:
        Tuple[str, str]: (tool_name, operation)
        
    Raises:
        ValueError: If key format is invalid
    """
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