"""
DEPRECATED: This module has been replaced by approval.py with a simpler design.

The new system (in approval.py) uses:
- ApprovalStore instead of ApprovalManager
- ApprovalScope (once/session/user) instead of ApprovalLevel
- No pattern matching - always ask on first use

This file is kept for backwards compatibility with existing tests.
New code should use the simplified approval.py module instead.

Old design: Multi-level approval management with pattern matching.
"""
import warnings
warnings.warn(
    "approval_manager is deprecated. Use approval.py with ApprovalStore instead.",
    DeprecationWarning,
    stacklevel=2
)

from typing import Dict, Tuple, Optional, Literal
from datetime import datetime, timedelta
import logging
import json

from .approval_models import (
    ApprovalDecision, ApprovalRecord, ApprovalLevel,
    RiskLevel
)
from agent.components.states import OpeyGraphState

logger = logging.getLogger(__name__)


def make_approval_key(tool_name: str, operation: str) -> str:
    """Create approval key - compat shim for old code."""
    return f"{tool_name}:{operation}"


def parse_approval_key(key: str) -> Tuple[str, str]:
    """Parse approval key - compat shim for old code."""
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid approval key format: {key}")
    return parts[0], parts[1]


class ApprovalManager:
    """
    Manages approval decisions across multiple persistence levels.
    Checks approvals in order: session → user → workspace.
    
    This is a per-session/per-user manager, not a singleton.
    Created for each OpeySession to track user-specific approval state.
    """
    
    def __init__(
        self, 
        redis_client=None, 
        workspace_config: Optional[Dict] = None,
        approval_ttl: Optional[timedelta] = None
    ):
        """
        Initialize approval manager.
        
        Args:
            redis_client: Redis client for user-level persistence (optional)
            workspace_config: Workspace-level approval rules (optional)
            approval_ttl: How long user-level approvals last (default: 24 hours)
        """
        self.redis = redis_client
        self.workspace_config = workspace_config or {}
        self.approval_ttl = approval_ttl or timedelta(hours=24)
        
        logger.debug("ApprovalManager initialized", extra={
            "has_redis": bool(redis_client),
            "has_workspace_config": bool(workspace_config),
            "approval_ttl_hours": self.approval_ttl.total_seconds() / 3600
        })
    
    async def check_approval(
        self,
        state: OpeyGraphState,
        tool_name: str,
        operation: str,
        config: dict
    ) -> Literal["approved", "denied", "requires_approval"]:
        """
        Check if operation is pre-approved at any level.
        Returns decision without user interaction if already approved.
        
        Checks in order:
        1. Session-level (in graph state) - fastest
        2. User-level (in Redis) - persists across sessions
        3. Workspace-level (in config) - global rules
        
        Args:
            state: Current graph state
            tool_name: Name of the tool
            operation: Operation being performed (e.g., "POST", "DELETE")
            config: LangGraph config with thread_id
            
        Returns:
            "approved" - Already approved, proceed
            "denied" - Already denied, reject
            "requires_approval" - Need to ask user
        """
        key = make_approval_key(tool_name, operation)
        thread_id = config.get("configurable", {}).get("thread_id")
        
        # Level 1: Session-level (stored in state)
        session_result = self._check_session_approval(state, key)
        if session_result is not None:
            logger.info("Session-level approval found", extra={
                "tool_name": tool_name,
                "operation": operation,
                "approved": session_result,
                "thread_id": thread_id
            })
            return "approved" if session_result else "denied"
        
        # Level 2: User-level (stored in Redis)
        if self.redis and thread_id:
            user_result = await self._check_user_approval(thread_id, key)
            if user_result is not None:
                logger.info("User-level approval found", extra={
                    "tool_name": tool_name,
                    "operation": operation,
                    "approved": user_result,
                    "thread_id": thread_id
                })
                
                # Promote to session-level for faster future checks
                if session_result is None:
                    self._save_session_approval(state, key, user_result)
                
                return "approved" if user_result else "denied"
        
        # Level 3: Workspace-level (stored in config/env)
        workspace_result = self._check_workspace_approval(tool_name, operation)
        if workspace_result is not None:
            logger.info("Workspace-level approval found", extra={
                "tool_name": tool_name,
                "operation": operation,
                "approved": workspace_result,
                "thread_id": thread_id
            })
            
            # Promote to session-level for faster future checks
            if session_result is None:
                self._save_session_approval(state, key, workspace_result)
            
            return "approved" if workspace_result else "denied"
        
        # No pre-approval found at any level
        logger.debug("No pre-approval found, requires user approval", extra={
            "tool_name": tool_name,
            "operation": operation,
            "thread_id": thread_id
        })
        return "requires_approval"
    
    def _check_session_approval(
        self,
        state: OpeyGraphState,
        key: str
    ) -> Optional[bool]:
        """Check session-level approval from graph state"""
        session_approvals = state.get("session_approvals", {})
        if key not in session_approvals:
            return None
        
        # Check if approval is still fresh (hasn't expired)
        approval_timestamps = state.get("approval_timestamps", {})
        approval_timestamp = approval_timestamps.get(key)
        
        if approval_timestamp:
            age = datetime.now() - approval_timestamp
            if age > self.approval_ttl:
                logger.debug("Session approval expired", extra={
                    "key": key,
                    "age_hours": age.total_seconds() / 3600
                })
                return None
        
        return session_approvals[key]
    
    async def _check_user_approval(
        self,
        thread_id: str,
        key: str
    ) -> Optional[bool]:
        """Check user-level approval from Redis"""
        if not self.redis:
            return None
        
        # Parse key to get tool_name and operation
        tool_name, operation = parse_approval_key(key)
        redis_key = f"approval:user:{thread_id}:{tool_name}:{operation}"
        
        try:
            result = await self.redis.get(redis_key)
            if result is None:
                return None
            
            # Parse stored data
            data = json.loads(result)
            approved = data.get("approved")
            timestamp_str = data.get("timestamp")
            
            if not timestamp_str:
                logger.warning("User approval missing timestamp", extra={
                    "redis_key": redis_key
                })
                return None
            
            timestamp = datetime.fromisoformat(timestamp_str)
            
            # Check if expired
            age = datetime.now() - timestamp
            if age > self.approval_ttl:
                logger.debug("User approval expired, deleting", extra={
                    "redis_key": redis_key,
                    "age_hours": age.total_seconds() / 3600
                })
                await self.redis.delete(redis_key)
                return None
            
            return approved
            
        except json.JSONDecodeError as e:
            logger.error("Failed to decode user approval from Redis", extra={
                "redis_key": redis_key,
                "error": str(e)
            })
            return None
        except Exception as e:
            logger.error("Error checking user approval", extra={
                "redis_key": redis_key,
                "error": str(e)
            }, exc_info=True)
            return None
    
    def _check_workspace_approval(
        self,
        tool_name: str,
        operation: str
    ) -> Optional[bool]:
        """
        Check workspace-level approval from configuration.
        
        Workspace config format:
        {
            "obp_requests": {
                "auto_approve": [
                    {"method": "GET", "path": "*"},
                    {"method": "POST", "path": "/obp/*/accounts/*/views"}
                ],
                "always_deny": [
                    {"method": "DELETE", "path": "/obp/*/banks/*"}
                ]
            }
        }
        """
        tool_config = self.workspace_config.get(tool_name, {})
        
        # Check auto_approve rules
        auto_approve = tool_config.get("auto_approve", [])
        for rule in auto_approve:
            if self._matches_workspace_rule(operation, rule):
                logger.debug("Matched workspace auto_approve rule", extra={
                    "tool_name": tool_name,
                    "operation": operation,
                    "rule": rule
                })
                return True
        
        # Check always_deny rules
        always_deny = tool_config.get("always_deny", [])
        for rule in always_deny:
            if self._matches_workspace_rule(operation, rule):
                logger.debug("Matched workspace always_deny rule", extra={
                    "tool_name": tool_name,
                    "operation": operation,
                    "rule": rule
                })
                return False
        
        # No matching workspace rule
        return None
    
    def _matches_workspace_rule(self, operation: str, rule: dict) -> bool:
        """Check if operation matches a workspace rule"""
        rule_method = rule.get("method", "*").upper()
        
        if rule_method == "*":
            return True
        
        return operation.upper() == rule_method
    
    async def save_approval(
        self,
        state: OpeyGraphState,
        tool_name: str,
        operation: str,
        decision: ApprovalDecision,
        config: dict
    ) -> None:
        """
        Save approval at specified level.
        
        Args:
            state: Current graph state
            tool_name: Name of the tool
            operation: Operation being performed
            decision: User's approval decision (includes level)
            config: LangGraph config with thread_id
        """
        key = make_approval_key(tool_name, operation)
        thread_id = config.get("configurable", {}).get("thread_id")
        
        logger.info("Saving approval", extra={
            "tool_name": tool_name,
            "operation": operation,
            "approved": decision.approved,
            "level": decision.approval_level.value,
            "thread_id": thread_id
        })
        
        if decision.approval_level == ApprovalLevel.ONCE:
            # Don't persist, just for this execution
            logger.debug("ONCE level approval - not persisting")
            return
        
        elif decision.approval_level == ApprovalLevel.SESSION:
            self._save_session_approval(state, key, decision.approved)
        
        elif decision.approval_level == ApprovalLevel.USER:
            if self.redis and thread_id:
                await self._save_user_approval(thread_id, key, decision.approved)
            else:
                logger.warning("Cannot save user-level approval: Redis not available")
                # Fallback to session level
                self._save_session_approval(state, key, decision.approved)
    
    def _save_session_approval(
        self,
        state: OpeyGraphState,
        key: str,
        approved: bool
    ) -> None:
        """Save approval to session state (in-memory, persisted by checkpointer)"""
        # Initialize dicts if they don't exist
        if "session_approvals" not in state:
            state["session_approvals"] = {}
        if "approval_timestamps" not in state:
            state["approval_timestamps"] = {}
        
        state["session_approvals"][key] = approved
        state["approval_timestamps"][key] = datetime.now()
        
        logger.info("Saved session-level approval", extra={
            "key": key,
            "approved": approved
        })
    
    async def _save_user_approval(
        self,
        thread_id: str,
        key: str,
        approved: bool
    ) -> None:
        """Save approval to Redis for user-level persistence"""
        # Parse key to get tool_name and operation
        tool_name, operation = parse_approval_key(key)
        redis_key = f"approval:user:{thread_id}:{tool_name}:{operation}"
        data = {
            "approved": approved,
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "operation": operation
        }
        
        try:
            # Set with TTL
            await self.redis.setex(
                redis_key,
                int(self.approval_ttl.total_seconds()),
                json.dumps(data)
            )
            logger.info("Saved user-level approval to Redis", extra={
                "redis_key": redis_key,
                "approved": approved,
                "ttl_hours": self.approval_ttl.total_seconds() / 3600
            })
        except Exception as e:
            logger.error("Failed to save user approval to Redis", extra={
                "redis_key": redis_key,
                "error": str(e)
            }, exc_info=True)
            raise
    
    async def clear_approvals(
        self,
        state: OpeyGraphState,
        config: dict,
        level: Optional[ApprovalLevel] = None
    ) -> None:
        """
        Clear approvals at specified level.
        Useful for "revoke all approvals" functionality.
        
        Args:
            state: Current graph state
            config: LangGraph config with thread_id
            level: Which level to clear (None = all levels)
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        
        if level is None or level == ApprovalLevel.SESSION:
            state["session_approvals"] = {}
            state["approval_timestamps"] = {}
            logger.info("Cleared session-level approvals")
        
        if level is None or level == ApprovalLevel.USER:
            if self.redis and thread_id:
                # Clear all user-level approvals for this thread
                pattern = f"approval:user:{thread_id}:*"
                try:
                    keys = await self.redis.keys(pattern)
                    if keys:
                        await self.redis.delete(*keys)
                        logger.info("Cleared user-level approvals", extra={
                            "thread_id": thread_id,
                            "count": len(keys)
                        })
                except Exception as e:
                    logger.error("Failed to clear user approvals", extra={
                        "thread_id": thread_id,
                        "error": str(e)
                    }, exc_info=True)
    
    def get_approval_summary(self, state: OpeyGraphState) -> Dict:
        """
        Get summary of current approval state.
        Useful for debugging and showing user what they've approved.
        """
        session_approvals = state.get("session_approvals", {})
        approval_timestamps = state.get("approval_timestamps", {})
        
        summary = {
            "session_approvals": [],
            "total_count": len(session_approvals)
        }
        
        for key, approved in session_approvals.items():
            tool_name, operation = parse_approval_key(key)
            timestamp = approval_timestamps.get(key)
            
            summary["session_approvals"].append({
                "tool_name": tool_name,
                "operation": operation,
                "approved": approved,
                "timestamp": timestamp.isoformat() if timestamp else None,
                "age_minutes": (
                    (datetime.now() - timestamp).total_seconds() / 60 
                    if timestamp else None
                )
            })
        
        return summary
