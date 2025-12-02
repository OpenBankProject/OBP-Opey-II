"""
Tests for the tool approval system.

Tests cover:
- Approval key generation and parsing
- ApprovalManager approval checking at different levels
- ToolRegistry approval pattern matching
- State persistence with string keys (JSON serialization)
- Integration with LangGraph checkpointing
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import json

from src.agent.components.states import (
    OpeyGraphState, 
    make_approval_key, 
    parse_approval_key,
    merge_dicts
)
from src.agent.components.tools.approval_manager import ApprovalManager
from src.agent.components.tools.approval_models import (
    ApprovalDecision,
    ApprovalLevel,
    RiskLevel,
    ApprovalAction,
    ApprovalPattern,
    ToolApprovalMetadata
)
from src.agent.components.tools.tool_registry import ToolRegistry, RegisteredTool
from langchain_core.tools import BaseTool


class TestApprovalKeyFunctions:
    """Test approval key generation and parsing"""
    
    def test_make_approval_key_basic(self):
        """Test basic approval key creation"""
        key = make_approval_key("obp_requests", "POST")
        assert key == "obp_requests:POST"
        assert isinstance(key, str)
    
    def test_make_approval_key_with_path(self):
        """Test approval key with path in operation"""
        key = make_approval_key("obp_requests", "POST:/obp/v5.1.0/banks")
        assert key == "obp_requests:POST:/obp/v5.1.0/banks"
    
    def test_parse_approval_key_basic(self):
        """Test parsing approval key back to tuple"""
        tool_name, operation = parse_approval_key("obp_requests:POST")
        assert tool_name == "obp_requests"
        assert operation == "POST"
    
    def test_parse_approval_key_with_path(self):
        """Test parsing approval key with path"""
        tool_name, operation = parse_approval_key("obp_requests:POST:/obp/v5.1.0/banks")
        assert tool_name == "obp_requests"
        assert operation == "POST:/obp/v5.1.0/banks"
    
    def test_parse_approval_key_invalid(self):
        """Test parsing invalid approval key raises error"""
        with pytest.raises(ValueError, match="Invalid approval key format"):
            parse_approval_key("invalid_key_no_colon")
    
    def test_approval_key_roundtrip(self):
        """Test that make and parse are inverses"""
        tool_name = "obp_requests"
        operation = "POST:/obp/v5.1.0/banks"
        
        key = make_approval_key(tool_name, operation)
        parsed_tool, parsed_op = parse_approval_key(key)
        
        assert parsed_tool == tool_name
        assert parsed_op == operation


class TestMergeDicts:
    """Test dictionary merging for state channels"""
    
    def test_merge_dicts_empty(self):
        """Test merging empty dictionaries"""
        result = merge_dicts({}, {})
        assert result == {}
    
    def test_merge_dicts_basic(self):
        """Test basic dictionary merge"""
        left = {"a": 1, "b": 2}
        right = {"c": 3, "d": 4}
        result = merge_dicts(left, right)
        
        assert result == {"a": 1, "b": 2, "c": 3, "d": 4}
    
    def test_merge_dicts_override(self):
        """Test that right dict takes precedence"""
        left = {"a": 1, "b": 2}
        right = {"b": 99, "c": 3}
        result = merge_dicts(left, right)
        
        assert result == {"a": 1, "b": 99, "c": 3}
    
    def test_merge_dicts_with_string_keys(self):
        """Test merging with approval-style string keys"""
        left = {"tool1:op1": True, "tool2:op2": False}
        right = {"tool3:op3": True}
        result = merge_dicts(left, right)
        
        assert result == {
            "tool1:op1": True,
            "tool2:op2": False,
            "tool3:op3": True
        }


class TestApprovalManager:
    """Test ApprovalManager functionality"""
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client"""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        redis.keys = AsyncMock(return_value=[])
        redis.delete = AsyncMock()
        return redis
    
    @pytest.fixture
    def approval_manager(self, mock_redis):
        """Create ApprovalManager with mock Redis"""
        workspace_config = {
            "obp_requests": {
                "auto_approve": [
                    {"method": "GET", "path": "*"}
                ],
                "always_deny": [
                    {"method": "DELETE", "path": "/obp/*/banks/*"}
                ]
            }
        }
        return ApprovalManager(
            redis_client=mock_redis,
            workspace_config=workspace_config,
            approval_ttl=timedelta(hours=24)
        )
    
    @pytest.fixture
    def mock_state(self):
        """Create mock OpeyGraphState"""
        state = {
            "messages": [],
            "session_approvals": {},
            "approval_timestamps": {}
        }
        return state
    
    @pytest.mark.asyncio
    async def test_check_approval_not_found(self, approval_manager, mock_state):
        """Test checking approval when none exists"""
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "requires_approval"
    
    @pytest.mark.asyncio
    async def test_check_approval_session_level(self, approval_manager, mock_state):
        """Test checking session-level approval"""
        # Add session approval
        key = make_approval_key("obp_requests", "POST")
        mock_state["session_approvals"][key] = True
        mock_state["approval_timestamps"][key] = datetime.now()
        
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "approved"
    
    @pytest.mark.asyncio
    async def test_check_approval_session_level_denied(self, approval_manager, mock_state):
        """Test checking denied session-level approval"""
        # Add session denial
        key = make_approval_key("obp_requests", "DELETE")
        mock_state["session_approvals"][key] = False
        mock_state["approval_timestamps"][key] = datetime.now()
        
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="DELETE",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "denied"
    
    @pytest.mark.asyncio
    async def test_check_approval_expired(self, approval_manager, mock_state):
        """Test that expired approvals are ignored"""
        # Add expired approval
        key = make_approval_key("obp_requests", "POST")
        mock_state["session_approvals"][key] = True
        mock_state["approval_timestamps"][key] = datetime.now() - timedelta(hours=25)
        
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "requires_approval"
    
    @pytest.mark.asyncio
    async def test_check_approval_workspace_level(self, approval_manager, mock_state):
        """Test workspace-level auto-approval"""
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="GET",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "approved"
    
    @pytest.mark.asyncio
    async def test_check_approval_workspace_deny(self, approval_manager, mock_state):
        """Test workspace-level always_deny"""
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="DELETE",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "denied"
    
    @pytest.mark.asyncio
    async def test_save_approval_session_level(self, approval_manager, mock_state):
        """Test saving session-level approval"""
        decision = ApprovalDecision(
            approved=True,
            approval_level=ApprovalLevel.SESSION
        )
        
        await approval_manager.save_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            decision=decision,
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        key = make_approval_key("obp_requests", "POST")
        assert key in mock_state["session_approvals"]
        assert mock_state["session_approvals"][key] is True
        assert key in mock_state["approval_timestamps"]
    
    @pytest.mark.asyncio
    async def test_save_approval_once_not_persisted(self, approval_manager, mock_state):
        """Test that ONCE approvals are not persisted"""
        decision = ApprovalDecision(
            approved=True,
            approval_level=ApprovalLevel.ONCE
        )
        
        await approval_manager.save_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            decision=decision,
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        # Should not be in state
        key = make_approval_key("obp_requests", "POST")
        assert key not in mock_state["session_approvals"]
    
    @pytest.mark.asyncio
    async def test_save_approval_user_level(self, approval_manager, mock_redis, mock_state):
        """Test saving user-level approval to Redis"""
        decision = ApprovalDecision(
            approved=True,
            approval_level=ApprovalLevel.USER
        )
        
        await approval_manager.save_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            decision=decision,
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        # Verify Redis was called
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        
        # Check Redis key format
        assert "approval:user:test-thread:obp_requests:POST" in str(args)
    
    @pytest.mark.asyncio
    async def test_check_user_approval_from_redis(self, approval_manager, mock_redis, mock_state):
        """Test checking user-level approval from Redis"""
        # Mock Redis response
        approval_data = {
            "approved": True,
            "timestamp": datetime.now().isoformat(),
            "tool_name": "obp_requests",
            "operation": "POST"
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(approval_data))
        
        result = await approval_manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        assert result == "approved"
        mock_redis.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_clear_session_approvals(self, approval_manager, mock_state):
        """Test clearing session-level approvals"""
        # Add some approvals
        key1 = make_approval_key("obp_requests", "POST")
        key2 = make_approval_key("obp_requests", "PUT")
        mock_state["session_approvals"][key1] = True
        mock_state["session_approvals"][key2] = True
        mock_state["approval_timestamps"][key1] = datetime.now()
        mock_state["approval_timestamps"][key2] = datetime.now()
        
        await approval_manager.clear_approvals(
            state=mock_state,
            config={"configurable": {"thread_id": "test-thread"}},
            level=ApprovalLevel.SESSION
        )
        
        assert mock_state["session_approvals"] == {}
        assert mock_state["approval_timestamps"] == {}
    
    def test_get_approval_summary(self, approval_manager, mock_state):
        """Test getting approval summary"""
        # Add some approvals
        key1 = make_approval_key("obp_requests", "POST")
        key2 = make_approval_key("retrieve_endpoints", "GET")
        mock_state["session_approvals"][key1] = True
        mock_state["session_approvals"][key2] = True
        mock_state["approval_timestamps"][key1] = datetime.now()
        mock_state["approval_timestamps"][key2] = datetime.now()
        
        summary = approval_manager.get_approval_summary(mock_state)
        
        assert summary["total_count"] == 2
        assert len(summary["session_approvals"]) == 2


class TestToolRegistry:
    """Test ToolRegistry approval pattern matching"""
    
    @pytest.fixture
    def mock_tool(self):
        """Create a mock LangChain tool"""
        tool = Mock(spec=BaseTool)
        tool.name = "obp_requests"
        tool.description = "Make HTTP requests to OBP API"
        return tool
    
    @pytest.fixture
    def tool_registry(self):
        """Create a ToolRegistry instance"""
        return ToolRegistry()
    
    def test_register_tool(self, tool_registry, mock_tool):
        """Test registering a tool with approval metadata"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.DANGEROUS,
            patterns=[
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="Read-only"
                )
            ]
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        
        registered = tool_registry.get_tool("obp_requests")
        assert registered is not None
        assert registered.tool.name == "obp_requests"
        assert registered.metadata.default_risk_level == RiskLevel.DANGEROUS
    
    def test_should_require_approval_auto_approve(self, tool_registry, mock_tool):
        """Test auto-approval pattern matching"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.DANGEROUS,
            patterns=[
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE
                )
            ]
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        
        result = tool_registry.should_require_approval(
            "obp_requests",
            {"method": "GET", "path": "/obp/v5.1.0/banks"}
        )
        
        assert result is False
    
    def test_should_require_approval_require_approval(self, tool_registry, mock_tool):
        """Test require approval pattern matching"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.SAFE,
            patterns=[
                ApprovalPattern(
                    method="POST",
                    path="*",
                    action=ApprovalAction.REQUIRE_APPROVAL
                )
            ]
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        
        result = tool_registry.should_require_approval(
            "obp_requests",
            {"method": "POST", "path": "/obp/v5.1.0/banks"}
        )
        
        assert result is True
    
    def test_should_require_approval_pattern_priority(self, tool_registry, mock_tool):
        """Test that patterns are checked in order"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.DANGEROUS,
            patterns=[
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="Read-only"
                ),
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.REQUIRE_APPROVAL,
                    reason="Default"
                )
            ]
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        
        # GET should be auto-approved (first pattern)
        result = tool_registry.should_require_approval(
            "obp_requests",
            {"method": "GET", "path": "/obp/v5.1.0/banks"}
        )
        assert result is False
        
        # POST should require approval (second pattern)
        result = tool_registry.should_require_approval(
            "obp_requests",
            {"method": "POST", "path": "/obp/v5.1.0/banks"}
        )
        assert result is True
    
    def test_build_approval_context(self, tool_registry, mock_tool):
        """Test building approval context"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.DANGEROUS,
            available_approval_levels=[ApprovalLevel.ONCE, ApprovalLevel.SESSION, ApprovalLevel.USER]
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        
        context = tool_registry.build_approval_context(
            tool_name="obp_requests",
            tool_call_id="test-call-123",
            tool_args={"method": "POST", "path": "/obp/v5.1.0/banks"},
            session_history={"similar_count": 2, "last_similar_approval": datetime.now()}
        )
        
        assert context.tool_name == "obp_requests"
        assert context.tool_call_id == "test-call-123"
        assert context.risk_level in [RiskLevel.DANGEROUS, RiskLevel.CRITICAL]
        assert context.similar_operations_count == 2
        assert ApprovalLevel.SESSION in context.available_approval_levels
    
    def test_risk_assessment_get_safe(self, tool_registry, mock_tool):
        """Test risk assessment for GET requests"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.MODERATE
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        registered = tool_registry.get_tool("obp_requests")
        
        risk = registered._assess_risk({"method": "GET", "path": "/obp/v5.1.0/banks"})
        assert risk == RiskLevel.SAFE
    
    def test_risk_assessment_delete_critical(self, tool_registry, mock_tool):
        """Test risk assessment for DELETE requests"""
        metadata = ToolApprovalMetadata(
            tool_name="obp_requests",
            description="Make HTTP requests",
            default_risk_level=RiskLevel.MODERATE
        )
        
        tool_registry.register_tool(mock_tool, metadata)
        registered = tool_registry.get_tool("obp_requests")
        
        risk = registered._assess_risk({"method": "DELETE", "path": "/obp/v5.1.0/banks/test"})
        assert risk == RiskLevel.CRITICAL


class TestStateJSONSerialization:
    """Test that state with string keys can be serialized to JSON"""
    
    def test_session_approvals_json_serializable(self):
        """Test that session_approvals can be serialized to JSON"""
        state = {
            "session_approvals": {
                "obp_requests:POST": True,
                "obp_requests:PUT": False,
                "retrieve_endpoints:GET": True
            }
        }
        
        # Should not raise
        json_str = json.dumps(state)
        decoded = json.loads(json_str)
        
        assert decoded["session_approvals"]["obp_requests:POST"] is True
        assert decoded["session_approvals"]["obp_requests:PUT"] is False
    
    def test_approval_timestamps_json_serializable(self):
        """Test that approval_timestamps can be serialized with ISO format"""
        now = datetime.now()
        state = {
            "approval_timestamps": {
                "obp_requests:POST": now.isoformat()
            }
        }
        
        # Should not raise
        json_str = json.dumps(state)
        decoded = json.loads(json_str)
        
        # Should be able to reconstruct datetime
        timestamp_str = decoded["approval_timestamps"]["obp_requests:POST"]
        reconstructed = datetime.fromisoformat(timestamp_str)
        
        assert isinstance(reconstructed, datetime)
    
    def test_complete_state_json_serializable(self):
        """Test that complete approval state structure is JSON serializable"""
        state = {
            "messages": [],
            "session_approvals": {
                "obp_requests:POST:/obp/v5.1.0/banks": True,
                "obp_requests:DELETE:/obp/v5.1.0/banks/test": False
            },
            "approval_timestamps": {
                "obp_requests:POST:/obp/v5.1.0/banks": datetime.now().isoformat(),
                "obp_requests:DELETE:/obp/v5.1.0/banks/test": datetime.now().isoformat()
            },
            "conversation_summary": "Test conversation",
            "current_state": "idle",
            "aggregated_context": "",
            "total_tokens": 1000
        }
        
        # Should not raise
        json_str = json.dumps(state)
        decoded = json.loads(json_str)
        
        assert len(decoded["session_approvals"]) == 2
        assert len(decoded["approval_timestamps"]) == 2


class TestApprovalIntegration:
    """Integration tests for the complete approval flow"""
    
    @pytest.fixture
    def mock_state(self):
        """Create a fresh state for integration tests"""
        return {
            "messages": [],
            "session_approvals": {},
            "approval_timestamps": {},
            "conversation_summary": "",
            "current_state": "idle",
            "aggregated_context": "",
            "total_tokens": 0
        }
    
    @pytest.mark.asyncio
    async def test_approval_flow_session_level(self, mock_state):
        """Test complete approval flow at session level"""
        manager = ApprovalManager()
        
        # Step 1: Check approval (should require approval)
        result = await manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST:/obp/v5.1.0/banks",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        assert result == "requires_approval"
        
        # Step 2: User approves at session level
        decision = ApprovalDecision(
            approved=True,
            approval_level=ApprovalLevel.SESSION
        )
        
        await manager.save_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST:/obp/v5.1.0/banks",
            decision=decision,
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        # Step 3: Check approval again (should be approved)
        result = await manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="POST:/obp/v5.1.0/banks",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        assert result == "approved"
        
        # Step 4: Verify state contains approval
        key = make_approval_key("obp_requests", "POST:/obp/v5.1.0/banks")
        assert key in mock_state["session_approvals"]
        assert mock_state["session_approvals"][key] is True
    
    @pytest.mark.asyncio
    async def test_approval_denial_flow(self, mock_state):
        """Test denial flow"""
        manager = ApprovalManager()
        
        # User denies
        decision = ApprovalDecision(
            approved=False,
            approval_level=ApprovalLevel.SESSION
        )
        
        await manager.save_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="DELETE:/obp/v5.1.0/banks/test",
            decision=decision,
            config={"configurable": {"thread_id": "test-thread"}}
        )
        
        # Check approval (should be denied)
        result = await manager.check_approval(
            state=mock_state,
            tool_name="obp_requests",
            operation="DELETE:/obp/v5.1.0/banks/test",
            config={"configurable": {"thread_id": "test-thread"}}
        )
        assert result == "denied"
