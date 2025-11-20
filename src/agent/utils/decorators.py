from functools import wraps
from typing import Callable, Any, Optional
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
import logging

from utils.cancellation_manager import cancellation_manager
from agent.components.states import OpeyGraphState

logger = logging.getLogger(__name__)

def cancellable(
    message: str = "[Cancelled]",
    custom_returns: Optional[dict[str, Any]] = None,
    include_metadata: bool = False,
    preserve_state_keys: Optional[list[str]] = None
):
    """
    Add cancellation support to LangGraph nodes.
    
    Checks for cancellation before executing the node. If cancelled, returns
    early with a cancellation marker instead of executing the node logic.
    
    Args:
        message: Message to include in the cancelled AIMessage
        custom_returns: Custom state values to return on cancellation
        include_metadata: Whether to add cancellation metadata to state
        preserve_state_keys: List of state keys to preserve from input state
                            (useful to avoid corrupting counters/accumulators)
        
    Example:
        @cancellable(preserve_state_keys=["total_tokens"])
        async def my_node(state: OpeyGraphState, config: RunnableConfig):
            # Your logic here
            pass
    """
    
    def decorator(node_func: Callable) -> Callable:
        @wraps(node_func)
        async def wrapper(state: OpeyGraphState, config: RunnableConfig, **kwargs) -> dict[str, Any]:
            thread_id = config.get("configurable", {}).get("thread_id")
            
            if thread_id and await cancellation_manager.is_cancelled(thread_id):
                logger.info(f"Node '{node_func.__name__}' cancelled for thread {thread_id}")
                
                # Return simple cancellation message
                # Note: Orphaned tool calls are handled proactively by StreamManager._fix_orphaned_tool_calls()
                # before the next user message is processed, so we don't need to handle them here.
                result = {"messages": [AIMessage(content=message)]}
                
                if include_metadata:
                    result = {**result, "cancelled_at_node": node_func.__name__}
                
                # Preserve specified state keys from input state
                if preserve_state_keys:
                    for key in preserve_state_keys:
                        if key in state:
                            result[key] = state[key]
                
                if custom_returns:
                    result = {**result, **custom_returns}
                    
                return result
            
            return await node_func(state, config, **kwargs)
        
        return wrapper
    return decorator