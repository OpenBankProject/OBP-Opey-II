"""
Singleton instances and factory functions for approval system components.
Also re-exports the actual tool instances from the parent module.
"""
from typing import Optional
import logging

from .tool_registry import ToolRegistry
from .approval_manager import ApprovalManager

# Re-export the retrieval graphs and tools from their original locations
# This maintains backward compatibility for existing imports
from agent.components.retrieval.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.retrieval.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph

# Create the tool instances
endpoint_retrieval_tool = endpoint_retrieval_graph.as_tool(name="retrieve_endpoints")
glossary_retrieval_tool = glossary_retrieval_graph.as_tool(name="retrieve_glossary")

logger = logging.getLogger(__name__)

# Singleton ToolRegistry - shared across all sessions
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """
    Get the singleton ToolRegistry instance.
    
    The ToolRegistry is a singleton because:
    - Tools are application-level configuration
    - Same tools available to all users/sessions
    - Registered once at startup
    
    Returns:
        The global ToolRegistry instance
    """
    global _tool_registry
    
    if _tool_registry is None:
        logger.info("Initializing singleton ToolRegistry")
        _tool_registry = ToolRegistry()
    
    return _tool_registry


def create_approval_manager(
    redis_client=None,
    workspace_config: Optional[dict] = None
) -> ApprovalManager:
    """
    Create a new ApprovalManager instance.
    
    ApprovalManager is NOT a singleton because:
    - Tracks session-specific and user-specific approval state
    - Different users have different approval histories
    - Each OpeySession should have its own ApprovalManager
    
    Args:
        redis_client: Redis client for user-level persistence
        workspace_config: Workspace-level approval rules
        
    Returns:
        A new ApprovalManager instance
    """
    logger.debug("Creating new ApprovalManager instance")
    return ApprovalManager(
        redis_client=redis_client,
        workspace_config=workspace_config
    )


# Convenience function for getting the singleton
def get_or_create_tool_registry() -> ToolRegistry:
    """Alias for get_tool_registry() for clarity"""
    return get_tool_registry()


# For testing: reset the singleton
def _reset_tool_registry() -> None:
    """
    Reset the singleton ToolRegistry.
    WARNING: Only use in tests!
    """
    global _tool_registry
    _tool_registry = None
    logger.warning("ToolRegistry singleton reset (should only happen in tests)")
