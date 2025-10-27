# Integration Example: How to Use ToolRegistry and ApprovalManager

This document shows how to integrate the approval system into your `OpeySession`.

## 1. Registering Tools at Startup

In your application startup (e.g., `main.py` or `__init__.py`), register all tools once:

```python
# At application startup (runs once)
from agent.components.tools import get_tool_registry
from agent.components.tools.approval_models import (
    ToolApprovalMetadata, ApprovalPattern, ApprovalAction,
    RiskLevel, ApprovalLevel
)
from agent.components.tools import endpoint_retrieval_tool, glossary_retrieval_tool

def initialize_tools():
    """Called once at application startup"""
    registry = get_tool_registry()
    
    # Register endpoint retrieval tool (always safe)
    registry.register_tool(
        tool=endpoint_retrieval_tool,
        approval_metadata=ToolApprovalMetadata(
            tool_name="endpoint_retrieval_tool",
            description="Retrieve OBP API endpoint documentation",
            requires_auth=False,
            default_risk_level=RiskLevel.SAFE,
            patterns=[
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="Read-only operation"
                )
            ],
            can_be_pre_approved=True,
            available_approval_levels=[ApprovalLevel.ONCE, ApprovalLevel.SESSION]
        )
    )
    
    # Register glossary retrieval tool (always safe)
    registry.register_tool(
        tool=glossary_retrieval_tool,
        approval_metadata=ToolApprovalMetadata(
            tool_name="glossary_retrieval_tool",
            description="Retrieve glossary definitions",
            requires_auth=False,
            default_risk_level=RiskLevel.SAFE,
            patterns=[
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="Read-only operation"
                )
            ],
            can_be_pre_approved=True,
            available_approval_levels=[ApprovalLevel.ONCE, ApprovalLevel.SESSION]
        )
    )

# Call this in your main.py or app startup
initialize_tools()
```

## 2. Using in OpeySession

Update `src/service/opey_session.py`:

```python
from agent.components.tools import get_tool_registry, create_approval_manager
from service.redis_client import get_redis_client
import os

class OpeySession:
    def __init__(
        self, 
        request: Request, 
        session_data: Annotated[SessionData, Depends(session_verifier)], 
        session_id: Annotated[UUID, Depends(session_cookie)], 
        checkpointer: Annotated[BaseCheckpointSaver, Depends(get_global_checkpointer)]
    ):
        # ... existing code ...
        
        # Get the singleton ToolRegistry
        self.tool_registry = get_tool_registry()
        
        # Create per-session ApprovalManager
        redis_client = get_redis_client() if os.getenv("REDIS_URL") else None
        workspace_config = self._load_workspace_approval_config()
        self.approval_manager = create_approval_manager(
            redis_client=redis_client,
            workspace_config=workspace_config
        )
        
        # Register OBP tools with approval metadata
        if obp_api_mode != "NONE" and not self.is_anonymous:
            self._register_obp_tools()
        
        # Get tools from registry for graph
        base_tools = self.tool_registry.get_langchain_tools()
        
        # Build graph with tools
        self.graph = (OpeyAgentGraphBuilder()
                     .with_tools(base_tools)
                     .with_model(self._model_name, temperature=0.5)
                     .with_checkpointer(checkpointer)
                     .enable_human_review(obp_api_mode in ["DANGEROUS"])
                     .build())
    
    def _register_obp_tools(self):
        """Register OBP tools with approval metadata based on mode"""
        from agent.components.tools.approval_models import (
            ToolApprovalMetadata, ApprovalPattern, ApprovalAction,
            RiskLevel, ApprovalLevel
        )
        
        obp_api_mode = os.getenv("OBP_API_MODE")
        
        if obp_api_mode == "SAFE":
            # Only GET requests, auto-approve
            patterns = [
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="SAFE mode: read-only operations"
                )
            ]
        elif obp_api_mode == "DANGEROUS":
            # GET auto-approved, others require approval
            patterns = [
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="Read-only operation"
                ),
                ApprovalPattern(
                    method="POST",
                    path="/obp/*/accounts/*/views",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="View creation is low risk"
                ),
                ApprovalPattern(
                    method="DELETE",
                    path="/obp/*/banks/*",
                    action=ApprovalAction.ALWAYS_DENY,
                    reason="Cannot delete banks"
                ),
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.REQUIRE_APPROVAL,
                    reason="Default: require approval for modifications"
                )
            ]
        else:  # TEST mode
            patterns = [
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="TEST mode: auto-approve everything"
                )
            ]
        
        obp_tool = self.obp_requests.get_langchain_tool(obp_api_mode.lower())
        
        self.tool_registry.register_tool(
            tool=obp_tool,
            approval_metadata=ToolApprovalMetadata(
                tool_name="obp_requests",
                description="Make HTTP requests to OBP API",
                requires_auth=True,
                default_risk_level=RiskLevel.DANGEROUS,
                patterns=patterns,
                can_be_pre_approved=True,
                available_approval_levels=[
                    ApprovalLevel.ONCE,
                    ApprovalLevel.SESSION,
                    ApprovalLevel.USER
                ]
            )
        )
    
    def _load_workspace_approval_config(self) -> dict:
        """
        Load workspace-level approval configuration.
        Could be from environment, config file, or database.
        """
        # Example: Load from environment variable
        import json
        config_str = os.getenv("WORKSPACE_APPROVAL_CONFIG", "{}")
        try:
            return json.loads(config_str)
        except json.JSONDecodeError:
            logger.warning("Invalid WORKSPACE_APPROVAL_CONFIG, using empty config")
            return {}
```

## 3. Accessing in human_review_node

The `human_review_node` can now access these via the session:

```python
# In human_review_node
async def human_review_node(state: OpeyGraphState):
    # Get singletons/managers
    tool_registry = get_tool_registry()
    
    # Note: ApprovalManager needs to be passed somehow
    # Option 1: Pass via state
    approval_manager = state.get("approval_manager")
    
    # Option 2: Get from a context variable
    # Option 3: Inject via graph config
    
    # Use them
    if tool_registry.should_require_approval(tool_name, tool_args):
        context = tool_registry.build_approval_context(...)
        approval_status = await approval_manager.check_approval(...)
        # ...
```

## 4. Passing ApprovalManager to Nodes

There are a few ways to make `ApprovalManager` available to nodes:

### Option A: Store in Graph State (Recommended)
```python
class OpeyGraphState(MessagesState):
    # ... existing fields
    approval_manager: ApprovalManager  # Pass via state
```

### Option B: Use Context Variables
```python
from contextvars import ContextVar

approval_manager_context = ContextVar('approval_manager')

# In OpeySession
approval_manager_context.set(self.approval_manager)

# In human_review_node
approval_manager = approval_manager_context.get()
```

### Option C: Pass via Graph Config
```python
# When streaming
config = {
    'configurable': {
        'thread_id': thread_id,
        'approval_manager': approval_manager  # Pass here
    }
}

# In human_review_node
approval_manager = config.get('approval_manager')
```

**Recommendation: Option A (state)** is cleanest for LangGraph.

## 5. Example Workspace Config

Create an environment variable or config file:

```bash
# .env
WORKSPACE_APPROVAL_CONFIG='{
  "obp_requests": {
    "auto_approve": [
      {"method": "GET", "path": "*"},
      {"method": "POST", "path": "/obp/*/accounts/*/views"}
    ],
    "always_deny": [
      {"method": "DELETE", "path": "/obp/*/banks/*"},
      {"method": "DELETE", "path": "/obp/*/users/*"}
    ]
  }
}'
```

Or use a YAML file:

```yaml
# config/approval_rules.yaml
obp_requests:
  auto_approve:
    - method: GET
      path: "*"
      reason: "Read-only operations are safe"
    - method: POST
      path: "/obp/*/accounts/*/views"
      reason: "View creation is low risk"
  
  always_deny:
    - method: DELETE
      path: "/obp/*/banks/*"
      reason: "Cannot delete banks"
    - method: DELETE
      path: "/obp/*/users/*"
      reason: "Cannot delete users"
```

## Summary

### Singleton Pattern (ToolRegistry)
- ✅ One instance per application
- ✅ Tools registered at startup
- ✅ Shared across all sessions
- ✅ Thread-safe (no writes after startup)

### Per-Session Pattern (ApprovalManager)
- ✅ One instance per OpeySession
- ✅ Tracks user-specific approval state
- ✅ Access to session-specific Redis client
- ✅ Isolated between users

### Usage Flow
1. **Startup**: `initialize_tools()` registers all tools in singleton registry
2. **Per Request**: `OpeySession.__init__()` creates new `ApprovalManager`
3. **During Execution**: `human_review_node` uses both to check/save approvals
