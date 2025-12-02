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
    total_tokens = state.get("total_tokens", 0)  # Use .get() with default
    print(f"Total tokens in conversation: {total_tokens}")

    # If total_tokens is None or 0, we shouldn't summarize
    # (either counting failed or conversation was cancelled)
    if not total_tokens:
        print("Total tokens is 0 or not set, skipping summarization")
        return END

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
        
def needs_human_review(state:OpeyGraphState) -> Literal["human_review", END]:
    """
    Conditional edge to decide whther to route to the tools, return an answer from opey.
    If the tool called is obp_requests, we need to route to the human_review node to wait for human approval of tool
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # Check if the last message has tool_calls attribute (only AIMessage has this)
    # This prevents errors when last message is HumanMessage (e.g., after regeneration)
    tool_calls = getattr(last_message, 'tool_calls', None)
    
    if tool_calls:
        return "human_review"
    
    return END

