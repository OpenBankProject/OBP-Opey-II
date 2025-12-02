# Tool Approval System Integration Guide

## Architecture Overview

The new approval system integrates seamlessly with LangGraph's native `interrupt()` function and your existing conditional edges.

```
User Request
     ↓
   Opey Node (LLM decides to call tool)
     ↓
Conditional Edge: needs_human_review()
     ↓
[If requires review] → human_review_node
     ↓
├─ Check ApprovalManager (session/user/workspace)
├─ If pre-approved → continue to tools
└─ If not approved → interrupt() with rich context
     ↓
   Frontend receives approval request
     ↓
   User approves/denies
     ↓
   Graph resumes with decision
     ↓
   Save approval at chosen level
     ↓
   Continue to Tools Node or inject denial
```

## Key Components

### 1. **OpeyGraphState** (Enhanced)
```python
class OpeyGraphState(MessagesState):
    # Existing fields
    conversation_summary: str
    total_tokens: int
    
    # NEW: Approval tracking
    session_approvals: Dict[Tuple[str, str], bool]  # (tool_name, operation) -> approved
    approval_timestamps: Dict[Tuple[str, str], datetime]  # Track when approved
```

### 2. **human_review_node** (Dynamic Interrupt)
```python
async def human_review_node(state: OpeyGraphState):
    # 1. Get tool calls from state
    # 2. Check ApprovalManager for pre-existing approvals
    # 3. If not approved, use interrupt() with rich context
    # 4. Process user response
    # 5. Save approval at chosen level
    # 6. Return updated state
```

**Key Features:**
- ✅ Only interrupts when actually needed (not every time)
- ✅ Checks session/user/workspace approvals first
- ✅ Supports batch approvals
- ✅ Saves approval decisions at multiple levels

### 3. **needs_human_review** Edge (Unchanged)
```python
def needs_human_review(state: OpeyGraphState) -> Literal["human_review", "tools", END]:
    # Still decides IF we route to human_review_node
    # human_review_node decides if we actually interrupt
```

**Flow:**
1. Conditional edge checks if tool is potentially dangerous
2. Routes to `human_review_node` if yes
3. `human_review_node` checks ApprovalManager
4. Only interrupts if not pre-approved

### 4. **StreamManager._handle_approval** (Updated)
```python
async def _handle_approval(self, config: dict):
    # 1. Check graph state for __interrupt__
    # 2. Extract interrupt payload (ApprovalContext)
    # 3. Send to frontend via StreamEventFactory
```

**Key Change:** No longer manually checks state. Just forwards interrupt payloads to frontend.

### 5. **ApprovalManager** (New)
```python
class ApprovalManager:
    async def check_approval(state, tool_name, operation, config):
        # Check session → user → workspace
        # Return: "approved" | "denied" | "requires_approval"
    
    async def save_approval(state, tool_name, operation, decision, config):
        # Save at specified level (once/session/user/workspace)
```

### 6. **ToolRegistry** (New)
```python
class ToolRegistry:
    def should_require_approval(tool_name, tool_args) -> bool:
        # Pattern-based approval logic
    
    def build_approval_context(tool_name, tool_call_id, tool_args):
        # Build rich ApprovalContext
```

## Integration Flow

### First Request (No Pre-Approval)
```
1. User: "Create a bank account"
2. Opey decides to call obp_requests(POST)
3. needs_human_review() → "human_review" (because POST)
4. human_review_node():
   - ApprovalManager.check_approval() → "requires_approval"
   - ToolRegistry.build_approval_context() → rich context
   - interrupt(context) → pause execution
5. StreamManager detects __interrupt__
6. Frontend receives approval_request event
7. User approves with level="session"
8. Graph resumes via Command(resume={approved: true, level: "session"})
9. human_review_node saves approval:
   - state.session_approvals[("obp_requests", "POST")] = True
10. Continues to tools node
```

### Second Request (Pre-Approved)
```
1. User: "Create another account"
2. Opey decides to call obp_requests(POST)
3. needs_human_review() → "human_review" (because POST)
4. human_review_node():
   - ApprovalManager.check_approval() → "approved" (from session)
   - NO INTERRUPT - just returns state
5. Continues directly to tools node
6. No frontend approval request!
```

## Configuration Files

### Tool Registration (opey_session.py)
```python
from agent.components.tool_registry import ToolRegistry
from agent.components.approval_models import (
    ToolApprovalMetadata, ApprovalPattern, ApprovalAction,
    RiskLevel, ApprovalLevel
)

# Initialize registry
tool_registry = ToolRegistry()

# Register endpoint retrieval (always safe)
tool_registry.register(
    tool=endpoint_retrieval_tool,
    metadata=ToolApprovalMetadata(
        tool_name="endpoint_retrieval_tool",
        description="Retrieve OBP API endpoints",
        requires_auth=False,
        default_risk_level=RiskLevel.SAFE,
        patterns=[
            ApprovalPattern(
                method="*",
                path="*",
                action=ApprovalAction.AUTO_APPROVE,
                reason="Read-only operation"
            )
        ]
    )
)

# Register OBP requests (conditional approval)
tool_registry.register(
    tool=obp_requests_tool,
    metadata=ToolApprovalMetadata(
        tool_name="obp_requests",
        description="Make requests to OBP API",
        requires_auth=True,
        default_risk_level=RiskLevel.DANGEROUS,
        patterns=[
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
        ],
        available_approval_levels=[
            ApprovalLevel.ONCE,
            ApprovalLevel.SESSION,
            ApprovalLevel.USER
        ]
    )
)

# Get tools for graph
tools = tool_registry.get_langchain_tools()
```

## Updated StreamEventFactory

The `StreamEventFactory.approval_request()` should be enhanced to accept the new fields:

```python
@staticmethod
def approval_request(
    tool_name: str,
    tool_call_id: str,
    tool_input: Dict[str, Any],
    message: str,
    # Enhanced fields
    risk_level: str = "moderate",
    affected_resources: List[str] = None,
    reversible: bool = True,
    estimated_impact: str = "",
    similar_operations_count: int = 0,
    available_approval_levels: List[str] = None,
    default_approval_level: str = "once"
) -> ApprovalRequestEvent:
    return ApprovalRequestEvent(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_input=tool_input,
        message=message,
        risk_level=risk_level,
        affected_resources=affected_resources or [],
        reversible=reversible,
        estimated_impact=estimated_impact,
        similar_operations_count=similar_operations_count,
        available_approval_levels=available_approval_levels or ["once"],
        default_approval_level=default_approval_level
    )
```

## Frontend Integration

The frontend will receive enhanced approval events:

```typescript
interface ApprovalRequestEvent {
  type: "approval_request";
  tool_name: string;
  tool_call_id: string;
  tool_input: Record<string, any>;
  message: string;
  
  // Enhanced fields
  risk_level: "safe" | "moderate" | "dangerous" | "critical";
  affected_resources: string[];
  reversible: boolean;
  estimated_impact: string;
  similar_operations_count: number;
  available_approval_levels: ("once" | "session" | "user" | "workspace")[];
  default_approval_level: "once" | "session" | "user" | "workspace";
}
```

Frontend can now show:
- Risk indicator (🟢 safe, 🟡 moderate, 🟠 dangerous, 🔴 critical)
- Affected resources list
- "This action can be undone" or "This action is permanent"
- "You've approved 3 similar operations today"
- Dropdown for approval level: "Approve once", "Remember for this session", etc.

## Resuming After Approval

When user approves in the frontend:

```python
# Frontend sends to /approval/{thread_id}
approval_response = ToolCallApproval(
    approval="approve",
    tool_call_id="call_123",
    approval_level="session",  # NEW
    feedback=None  # Optional user comment
)

# StreamManager processes this
stream_input = StreamInput(
    message="",
    thread_id=thread_id,
    tool_call_approval=approval_response
)

# Graph resumes, human_review_node receives the response via interrupt()
```

## Benefits

1. **No Redundant Interrupts**: Once approved at session/user level, subsequent operations proceed without interruption
2. **Rich Context**: Users see risk level, affected resources, reversibility
3. **Flexible Persistence**: Choose approval level (once/session/user/workspace)
4. **Pattern-Based**: Configure approval rules without code changes
5. **LangGraph Native**: Uses `interrupt()` as intended, not hacky `interrupt_before`
6. **Backward Compatible**: Existing `needs_human_review` edge still works

## Migration Path

1. ✅ Create `approval_models.py` (data structures)
2. ✅ Create `tool_registry.py` (tool management)
3. ✅ Create `approval_manager.py` (multi-level checks)
4. ✅ Update `human_review_node` (use interrupt())
5. ✅ Update `OpeyGraphState` (add approval fields)
6. ✅ Remove `interrupt_before` from graph compilation
7. ⏳ Update `StreamEventFactory` (add new fields)
8. ⏳ Update `ApprovalRequestEvent` schema (add new fields)
9. ⏳ Register tools in `opey_session.py`
10. ⏳ Test the flow

## Testing

```python
# Test 1: First approval
response = await client.stream({"message": "Create a bank account"})
# Should receive approval_request with rich context

# Test 2: Approve at session level
approval = ToolCallApproval(approval="approve", tool_call_id="call_123", approval_level="session")
await client.approve_and_stream(thread_id, approval)

# Test 3: Second operation (should NOT request approval)
response = await client.stream({"message": "Create another account"})
# Should execute directly without approval request!

# Test 4: GET request (auto-approved by pattern)
response = await client.stream({"message": "List all banks"})
# Should never hit human_review_node
```
