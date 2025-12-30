"""
Simplified tool approval system.

Design principles:
- Always ask on first use (no pattern guessing)
- Remember at user-chosen scope (once/session/user)
- Track by tool name (arg-level approval can be added later)
- Support batch approval UI
"""

from enum import Enum
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Set, Dict, Any
import json
import logging

logger = logging.getLogger(__name__)


class ApprovalScope(str, Enum):
    """How long an approval lasts."""
    ONCE = "once"        # Single invocation
    SESSION = "session"  # Current conversation thread
    USER = "user"        # Persists across sessions (stored in Redis)


@dataclass
class ToolApproval:
    """
    Record of an approval grant.
    
    Currently tracks tool_name only. Structure supports adding
    arg-based approval later (e.g., "approve transfers up to $100").
    """
    tool_name: str
    scope: ApprovalScope
    granted_at: datetime = field(default_factory=datetime.now)
    
    # Reserved for future arg-level approval
    # e.g., {"max_amount": 100, "allowed_accounts": ["A", "B"]}
    constraints: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for Redis storage."""
        return {
            "tool_name": self.tool_name,
            "scope": self.scope.value,
            "granted_at": self.granted_at.isoformat(),
            "constraints": self.constraints,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolApproval":
        """Deserialize from Redis storage."""
        return cls(
            tool_name=data["tool_name"],
            scope=ApprovalScope(data["scope"]),
            granted_at=datetime.fromisoformat(data["granted_at"]),
            constraints=data.get("constraints", {}),
        )


@dataclass
class ApprovalRequest:
    """
    Information shown to user when requesting approval.
    
    Kept minimal - the tool name and args are usually enough context.
    """
    tool_name: str
    tool_call_id: str
    tool_args: Dict[str, Any]
    
    # Optional human-readable context
    description: Optional[str] = None


@dataclass
class ApprovalDecision:
    """User's response to an approval request."""
    approved: bool
    scope: ApprovalScope = ApprovalScope.ONCE
    
    # Future: user-modified args or constraints
    # modified_args: Optional[Dict[str, Any]] = None


class ApprovalStore:
    """
    Manages approval state across scopes.
    
    - ONCE: Not stored (implicit in allowing execution)
    - SESSION: Stored in graph state (passed via config)
    - USER: Stored in Redis with TTL
    """
    
    USER_APPROVAL_TTL = timedelta(days=7)
    REDIS_KEY_PREFIX = "user_approvals:"
    
    def __init__(
        self, 
        session_id: str,
        user_id: Optional[str] = None,
        redis_client: Optional[Any] = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self._redis = redis_client
        
        # Session-level approvals (in-memory, lost when session ends)
        self._session_approvals: Set[str] = set()
    
    def is_approved(self, tool_name: str) -> bool:
        """Check if tool is approved at any scope."""
        # Check session first (fastest)
        if tool_name in self._session_approvals:
            return True
        
        # Check user-level in Redis
        if self._redis and self.user_id:
            return self._check_user_approval(tool_name)
        
        return False
    
    def grant(self, tool_name: str, scope: ApprovalScope) -> None:
        """Grant approval at the specified scope."""
        approval = ToolApproval(tool_name=tool_name, scope=scope)
        
        if scope == ApprovalScope.ONCE:
            # ONCE approvals aren't stored - execution proceeds immediately
            logger.debug(f"One-time approval granted for {tool_name}")
            return
        
        if scope == ApprovalScope.SESSION:
            self._session_approvals.add(tool_name)
            logger.info(f"Session approval granted for {tool_name}")
            return
        
        if scope == ApprovalScope.USER:
            self._session_approvals.add(tool_name)  # Also add to session
            self._store_user_approval(approval)
            logger.info(f"User-level approval granted for {tool_name}")
            return
    
    def revoke(self, tool_name: str) -> None:
        """Revoke approval at all scopes."""
        self._session_approvals.discard(tool_name)
        
        if self._redis and self.user_id:
            self._remove_user_approval(tool_name)
        
        logger.info(f"Approval revoked for {tool_name}")
    
    def get_session_approvals(self) -> Set[str]:
        """Get all session-approved tools (for state persistence)."""
        return self._session_approvals.copy()
    
    def load_session_approvals(self, approvals: Set[str]) -> None:
        """Load session approvals from graph state."""
        self._session_approvals = set(approvals)
    
    # Redis operations for user-level approval
    
    def _redis_key(self) -> str:
        return f"{self.REDIS_KEY_PREFIX}{self.user_id}"
    
    def _check_user_approval(self, tool_name: str) -> bool:
        """Check Redis for user-level approval."""
        if not self._redis:
            return False
            
        try:
            data = self._redis.hget(self._redis_key(), tool_name)
            if data:
                approval = ToolApproval.from_dict(json.loads(data))
                # Could add expiry check here if needed
                return True
        except Exception as e:
            logger.warning(f"Redis read failed: {e}")
        return False
    
    def _store_user_approval(self, approval: ToolApproval) -> None:
        """Store approval in Redis with TTL."""
        if not self._redis or not self.user_id:
            logger.warning("Cannot store user approval: no Redis or user_id")
            return
        
        try:
            key = self._redis_key()
            self._redis.hset(key, approval.tool_name, json.dumps(approval.to_dict()))
            self._redis.expire(key, int(self.USER_APPROVAL_TTL.total_seconds()))
        except Exception as e:
            logger.error(f"Failed to store user approval: {e}")
    
    def _remove_user_approval(self, tool_name: str) -> None:
        """Remove approval from Redis."""
        if not self._redis or not self.user_id:
            return
        
        try:
            self._redis.hdel(self._redis_key(), tool_name)
        except Exception as e:
            logger.error(f"Failed to remove user approval: {e}")
