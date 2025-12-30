from langgraph.graph import MessagesState
from typing import Annotated, Dict, Set
import operator


def merge_dicts(left: dict, right: dict) -> dict:
    """Merge two dictionaries, with right taking precedence."""
    return {**left, **right}


def merge_sets(left: Set[str], right: Set[str]) -> Set[str]:
    """Merge two sets."""
    return left | right


class OpeyGraphState(MessagesState):
    """
    State for Opey agent with simplified approval tracking.
    
    Approval is tracked at tool name level only. More granular approval
    (per-operation) can be added later if needed.
    """
    conversation_summary: str
    current_state: str
    aggregated_context: str
    total_tokens: int
    
    # Session-level approvals: set of approved tool names
    # These are synced from ApprovalStore after each approval
    session_approvals: Annotated[Set[str], merge_sets]