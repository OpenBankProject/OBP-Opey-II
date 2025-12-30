"""
DEPRECATED: This module has been replaced by approval.py with a simpler design.

The new system uses:
- ApprovalScope (once/session/user) instead of complex ApprovalLevel + RiskLevel
- No pattern matching - always ask on first use
- ApprovalRequest/ApprovalDecision are simpler dataclasses

This file is kept for backwards compatibility with existing tests.
New code should use the simplified approval.py module instead.
"""
import warnings
warnings.warn(
    "approval_models is deprecated. Use approval.py instead.",
    DeprecationWarning,
    stacklevel=2
)

from typing import Literal, Dict, Any, List, Optional, Callable
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class RiskLevel(str, Enum):
    """Risk classification for tool operations"""
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


class ApprovalLevel(str, Enum):
    """Persistence level for approval decisions"""
    ONCE = "once"              # Single use
    SESSION = "session"        # Current thread/session
    USER = "user"              # All sessions for this user


class ApprovalAction(str, Enum):
    """Pattern-based approval actions"""
    AUTO_APPROVE = "auto_approve"
    REQUIRE_APPROVAL = "require_approval"
    ALWAYS_DENY = "always_deny"
    
    
class ApprovalPattern(BaseModel):
    """
    Pattern matching rule for tool approval.
    Uses glob patterns for flexible matching.
    """
    method: str = Field(
        default="*",
        description="HTTP method or operation type. Use '*' for any."
    )
    path: str = Field(
        default="*",
        description="Resource path pattern. Supports glob wildcards."
    )
    action: ApprovalAction = Field(
        description="Action to take when pattern matches"
    )
    reason: Optional[str] = Field(
        default=None,
        description="Explanation for this rule"
    )
    
    
class ToolApprovalMetadata(BaseModel):
    """
    Metadata describing a tool's approval requirements.
    Registered alongside each tool in the ToolRegistry.
    """
    tool_name: str
    description: str
    requires_auth: bool = Field(
        default=False,
        description="Whether tool requires authenticated user"
    )
    default_risk_level: RiskLevel = Field(
        default=RiskLevel.MODERATE,
        description="Default risk level if not dynamically determined i.e. for API requests built by the agent"
    )
    patterns: List[ApprovalPattern] = Field(
        default_factory=list,
        description="Pattern-based approval rules"
    )
    can_be_pre_approved: bool = Field(
        default=True,
        description="Whether this tool supports session/user-level approval"
    )
    available_approval_levels: List[ApprovalLevel] = Field(
        default_factory=lambda: [ApprovalLevel.ONCE, ApprovalLevel.SESSION],
        description="Which approval levels are available for this tool"
    )
    
    # Optional custom approval logic
    custom_approval_checker: Optional[Callable[[Dict[str, Any]], bool]] = Field(
        default=None,
        exclude=True,  # Don't serialize callable
        description="Custom function to determine if approval needed"
    )
    custom_context_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = Field(
        default=None,
        exclude=True,
        description="Custom function to build approval context"
    )
    
    
class ApprovalContext(BaseModel):
    """
    Rich context for approval decision.
    Provides all information needed for user to make informed choice.
    """
    # Core identification
    tool_name: str
    tool_call_id: str
    tool_input: Dict[str, Any]
    
    # Human-readable information
    operation_summary: str = Field(
        description="Clear description of what will happen"
    )
    message: str = Field(
        description="Detailed approval message"
    )
    
    # Risk assessment
    risk_level: RiskLevel
    affected_resources: List[str] = Field(
        default_factory=list,
        description="Resources that will be affected (e.g., 'Account gh.29.uk.123')"
    )
    reversible: bool = Field(
        default=True,
        description="Whether this operation can be easily undone"
    )
    estimated_impact: str = Field(
        default="",
        description="Expected outcome or side effects"
    )
    
    # Historical context
    similar_operations_count: int = Field(
        default=0,
        description="Number of similar operations in this session"
    )
    last_similar_approval: Optional[datetime] = Field(
        default=None,
        description="When user last approved similar operation"
    )
    
    # Approval options
    available_approval_levels: List[ApprovalLevel] = Field(
        description="Which approval levels user can choose"
    )
    default_approval_level: ApprovalLevel = Field(
        default=ApprovalLevel.ONCE,
        description="Suggested approval level"
    )
    
    # Additional metadata
    timestamp: datetime = Field(default_factory=datetime.now)


class ApprovalDecision(BaseModel):
    """User's approval decision"""
    approved: bool
    approval_level: ApprovalLevel = ApprovalLevel.ONCE
    modified_args: Optional[Dict[str, Any]] = Field(
        default=None,
        description="User-edited tool arguments (if supported)"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="User feedback/reason for decision"
    )
    
    
class ApprovalRecord(BaseModel):
    """Audit record of an approval event"""
    audit_id: str
    session_id: str
    user_id: Optional[str]
    tool_name: str
    tool_call_id: str
    tool_input: Dict[str, Any]
    context: ApprovalContext
    decision: ApprovalDecision
    timestamp: datetime = Field(default_factory=datetime.now)
    user_action: bool = Field(
        description="True if user clicked, False if auto-approved"
    )