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

    # Granted Consent-JWTs cached for reuse, keyed by "operation_id::bank_id" →
    # {"jwt": str, "created_at": float}. Lets a repeated operation reuse a still-valid
    # consent instead of re-prompting the user. Written only by consent_check_node,
    # which reads, updates and returns the whole dict (plain last-write-wins field).
    consent_jwts: Dict[str, dict]