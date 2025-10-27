"""
Example: LangGraph Node with Cooperative Cancellation Support

This example demonstrates how to modify a LangGraph node (specifically an LLM
streaming node) to support cooperative cancellation.

The key pattern is:
1. Check cancellation flag before starting expensive operations
2. Periodically check during long-running operations
3. Return partial results if cancelled
4. Mark state so downstream nodes know about cancellation
"""

import logging
from typing import Optional
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


# Example: Simple synchronous node with cancellation
async def simple_node_with_cancellation(state: dict, config: RunnableConfig) -> dict:
    """
    A simple node that checks for cancellation before doing work.
    
    This is the minimal pattern - check once before starting.
    """
    from utils.cancellation_manager import cancellation_manager
    
    thread_id = config["configurable"]["thread_id"]
    
    # Check cancellation before starting
    if await cancellation_manager.is_cancelled(thread_id):
        logger.info(f"Node skipped due to cancellation: {thread_id}")
        return {
            "was_cancelled": True,
            "skip_downstream": True
        }
    
    # Do your work here
    result = perform_some_operation(state)
    
    return {
        "result": result,
        "was_cancelled": False
    }


# Example: LLM streaming node with periodic cancellation checks
async def llm_streaming_node_with_cancellation(
    state: dict, 
    config: RunnableConfig
) -> dict:
    """
    An LLM streaming node that supports cooperative cancellation.
    
    This pattern checks cancellation:
    1. Before starting the LLM call
    2. Periodically during streaming (every N chunks)
    3. Returns partial content if cancelled
    """
    from utils.cancellation_manager import cancellation_manager
    
    thread_id = config["configurable"]["thread_id"]
    messages = state.get("messages", [])
    
    # Check if already cancelled before starting expensive LLM call
    if await cancellation_manager.is_cancelled(thread_id):
        logger.info(f"LLM node skipped due to cancellation: {thread_id}")
        return {
            "messages": [AIMessage(content="[Response cancelled by user before generation]")],
            "was_cancelled": True
        }
    
    # Initialize LLM with streaming
    llm = ChatOpenAI(model="gpt-4", streaming=True, temperature=0.7)
    
    # Stream tokens and check cancellation periodically
    full_content = ""
    chunk_count = 0
    check_interval = 5  # Check every 5 chunks to balance responsiveness vs overhead
    
    try:
        async for chunk in llm.astream(messages):
            chunk_count += 1
            
            # Accumulate content
            if hasattr(chunk, 'content') and chunk.content:
                full_content += chunk.content
            
            # Periodic cancellation check
            # Don't check every single chunk - that's expensive
            if chunk_count % check_interval == 0:
                if await cancellation_manager.is_cancelled(thread_id):
                    logger.info(
                        f"LLM streaming cancelled after {chunk_count} chunks for thread: {thread_id}"
                    )
                    # Return partial content with cancellation marker
                    return {
                        "messages": [AIMessage(content=full_content + " [cancelled]")],
                        "was_cancelled": True,
                        "partial_response": True,
                        "chunks_generated": chunk_count
                    }
        
        # Completed normally
        logger.info(f"LLM streaming completed normally with {chunk_count} chunks")
        return {
            "messages": [AIMessage(content=full_content)],
            "was_cancelled": False,
            "chunks_generated": chunk_count
        }
        
    except Exception as e:
        logger.error(f"Error during LLM streaming: {e}", exc_info=True)
        # Even on error, check if it was due to cancellation
        is_cancelled = await cancellation_manager.is_cancelled(thread_id)
        return {
            "messages": [AIMessage(content=full_content or "[Error during generation]")],
            "was_cancelled": is_cancelled,
            "error": str(e)
        }


# Example: Tool execution node with cancellation
async def tool_execution_node_with_cancellation(
    state: dict,
    config: RunnableConfig
) -> dict:
    """
    A tool execution node that checks cancellation before each tool call.
    
    Useful when executing multiple tools in sequence.
    """
    from utils.cancellation_manager import cancellation_manager
    
    thread_id = config["configurable"]["thread_id"]
    tool_calls = state.get("pending_tool_calls", [])
    results = []
    
    for i, tool_call in enumerate(tool_calls):
        # Check cancellation before each tool
        if await cancellation_manager.is_cancelled(thread_id):
            logger.info(
                f"Tool execution cancelled after {i}/{len(tool_calls)} tools"
            )
            return {
                "tool_results": results,
                "was_cancelled": True,
                "partial_results": True,
                "completed_tools": i
            }
        
        # Execute the tool
        result = await execute_tool(tool_call)
        results.append(result)
    
    return {
        "tool_results": results,
        "was_cancelled": False,
        "completed_tools": len(tool_calls)
    }


# Example: Conditional edge that respects cancellation
def should_continue_or_cancel(state: dict) -> str:
    """
    A conditional edge that routes to END if cancelled.
    
    This prevents further graph execution after cancellation.
    """
    if state.get("was_cancelled", False):
        return "END"
    
    # Your normal routing logic
    if state.get("some_condition"):
        return "continue_node"
    else:
        return "alternative_node"


# Example: Cleanup node that always runs
async def cleanup_node(state: dict, config: RunnableConfig) -> dict:
    """
    A cleanup node that runs regardless of cancellation.
    
    Use this pattern for essential operations like saving state,
    logging, or releasing resources.
    """
    thread_id = config["configurable"]["thread_id"]
    was_cancelled = state.get("was_cancelled", False)
    
    # Save messages to database (even partial ones)
    messages = state.get("messages", [])
    await save_messages_to_db(thread_id, messages, cancelled=was_cancelled)
    
    # Log the interaction
    logger.info(
        f"Conversation saved for thread {thread_id}",
        extra={
            "cancelled": was_cancelled,
            "message_count": len(messages)
        }
    )
    
    return {
        "saved": True,
        "timestamp": get_current_timestamp()
    }


# Example: Complete graph construction with cancellation support
def build_graph_with_cancellation():
    """
    Example of building a StateGraph with cancellation-aware nodes.
    """
    from langgraph.graph import StateGraph, END
    from typing import TypedDict
    
    class State(TypedDict):
        messages: list
        was_cancelled: bool
        tool_results: Optional[list]
    
    graph = StateGraph(State)
    
    # Add nodes
    graph.add_node("llm_generate", llm_streaming_node_with_cancellation)
    graph.add_node("execute_tools", tool_execution_node_with_cancellation)
    graph.add_node("cleanup", cleanup_node)
    
    # Add edges
    graph.set_entry_point("llm_generate")
    
    # Conditional edge that respects cancellation
    graph.add_conditional_edges(
        "llm_generate",
        should_continue_or_cancel,
        {
            "END": "cleanup",  # Go to cleanup if cancelled
            "continue_node": "execute_tools",
            "alternative_node": "cleanup"
        }
    )
    
    # Always end at cleanup
    graph.add_edge("execute_tools", "cleanup")
    graph.add_edge("cleanup", END)
    
    return graph.compile()


# Helper functions (mock implementations)
def perform_some_operation(state: dict) -> str:
    return "operation result"

async def execute_tool(tool_call: dict) -> dict:
    return {"status": "success", "result": "tool output"}

async def save_messages_to_db(thread_id: str, messages: list, cancelled: bool):
    pass

def get_current_timestamp() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


# Usage Example
"""
To use these patterns in your graph:

1. Modify your LLM node to use `llm_streaming_node_with_cancellation`
2. Add conditional edges that check `was_cancelled` 
3. Ensure cleanup/save nodes always run
4. Frontend sends POST to /stream/{thread_id}/stop when user clicks stop

Example flow:
- User starts streaming
- Frontend receives tokens
- User clicks "Stop" button
- Frontend calls POST /stream/{thread_id}/stop
- Backend sets cancellation flag
- LLM node checks flag on next chunk
- Node returns partial content with was_cancelled=True
- Graph routes to cleanup node
- Cleanup saves partial response
- Stream ends gracefully
"""
