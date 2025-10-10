from langgraph.graph import MessagesState
from pprint import pprint
from typing import Annotated, Dict, List, Optional, Tuple
from datetime import datetime
import operator

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
    # Key: (tool_name, operation) -> Value: approved/denied
    session_approvals: Annotated[Dict[Tuple[str, str], bool], operator.add]
    
    # Timestamps for approvals to check expiration
    approval_timestamps: Annotated[Dict[Tuple[str, str], datetime], operator.add]