"""
Tool loading and approval system.

Simplified architecture:
- MCPToolLoader: Loads tools from MCP servers
- ApprovalStore: Tracks user approval decisions (once/session/user scope)
- No pattern matching - always ask on first use, remember the answer
"""
from typing import Optional
import logging

from .approval import ApprovalStore, ApprovalScope, ApprovalRequest, ApprovalDecision
from .mcp_integration import MCPToolLoader, MCPServerConfig, OAuthConfig

logger = logging.getLogger(__name__)

__all__ = [
    # Approval system
    "ApprovalStore",
    "ApprovalScope", 
    "ApprovalRequest",
    "ApprovalDecision",
    # MCP integration
    "MCPToolLoader",
    "MCPServerConfig",
    "OAuthConfig",
    # Factory
    "create_approval_store",
]


def create_approval_store(
    session_id: str,
    user_id: Optional[str] = None,
    redis_client=None,
) -> ApprovalStore:
    """
    Create a new ApprovalStore for a session.
    
    Each session gets its own store because:
    - Session approvals are session-specific
    - User approvals are fetched from Redis per-session
    
    Args:
        session_id: Current session/thread ID
        user_id: User ID for cross-session approvals (optional)
        redis_client: Redis client for user-level persistence
        
    Returns:
        A new ApprovalStore instance
    """
    logger.debug(f"Creating ApprovalStore for session={session_id}, user={user_id}")
    return ApprovalStore(
        session_id=session_id,
        user_id=user_id,
        redis_client=redis_client,
    )
