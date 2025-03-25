import os

from agent.components.states import OpeyGraphState
from langgraph.graph import END
from typing import Literal 

def should_summarize(state: OpeyGraphState) -> Literal["summarize_conversation", END]:
    """
    Conditional edge to route to conversation summarizer or not
    """
    print("----- DECIDING WHETHER TO SUMMARIZE -----")
    messages = state["messages"]
    total_tokens = state["total_tokens"]
    print(f"Total tokens in conversation: {total_tokens}")

    if not total_tokens:
        raise ValueError("Total tokens not found in state")

    token_limit = os.getenv("CONVERSATION_TOKEN_LIMIT")
    if not token_limit:
        print("Token limit (CONVERSATION_TOKEN_LIMIT) not set in environment variables, defaulting to 50000")
        token_limit = 50000
        
    if total_tokens >= int(token_limit):
        print(f"Conversation more than token limit of {token_limit}, Descision: Summarize")
        return "summarize_conversation"
    # Otherwise we can just end
    print(f"Conversation less than token limit of {token_limit}, Descision: Do not summarize")
    return END
        
def needs_human_review(state:OpeyGraphState) -> Literal["human_review", "tools", END]:
    """
    Conditional edge to decide whther to route to the tools, return an answer from opey.
    If the tool called is obp_requests, we need to route to the human_review node to wait for human approval of tool
    """
    messages = state["messages"]
    tool_calls = messages[-1].tool_calls
    if not tool_calls:
        return END
    
    for tool_call in tool_calls:
        if (tool_call["name"] == "obp_requests"):
            if not (tool_call["args"]["method"] == "GET"):
                return "human_review"
            else:
                return "tools"
        return "tools"

