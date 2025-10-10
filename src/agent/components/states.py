from langgraph.graph import MessagesState
from pprint import pprint
from typing import Annotated, Dict, List, Optional, Tuple
import operator

### States
class OpeyGraphState(MessagesState):
    conversation_summary: str
    current_state: str
    aggregated_context: str
    total_tokens: int
    session_approvals: Annotated[Dict[Tuple[str,str], bool], operator.add]