# Approval System - Testing Guide

## Overview

This guide provides step-by-step instructions for testing the complete approval system integration.

## Prerequisites

1. **Environment Setup**:
   ```bash
   # Set OBP API mode
   export OBP_API_MODE=DANGEROUS  # For approval testing
   
   # Optional: Workspace approval config
   export WORKSPACE_APPROVAL_CONFIG='{}'
   
   # Optional: Redis for user-level approvals
   export REDIS_URL=redis://localhost:6379
   ```

2. **Start the service**:
   ```bash
   poetry run python src/run_service.py
   ```

## Test Scenarios

### Test 1: First Tool Call - Approval Request

**Purpose**: Verify that a dangerous operation triggers an approval request with rich context.

**Steps**:
1. Start a new chat session
2. Send a message that triggers an OBP POST request:
   ```
   "Create a new account view called 'test_view' for account XYZ at bank ABC"
   ```

**Expected Behavior**:
- Agent should plan to use `obp_requests` tool with POST method
- System routes to `human_review_node`
- Node checks `ToolRegistry` - POST requires approval (no auto-approve pattern match)
- Node checks `ApprovalManager` - no existing approval found
- Node calls `interrupt()` with rich approval context
- Frontend receives `ApprovalRequestEvent` with:
  ```json
  {
    "type": "approval_request",
    "tool_name": "obp_requests",
    "tool_call_id": "call_xxx",
    "tool_input": {"method": "POST", "path": "/obp/v5.0.0/banks/ABC/accounts/XYZ/views", ...},
    "message": "POST request to /obp/v5.0.0/banks/ABC/accounts/XYZ/views",
    "risk_level": "moderate",
    "affected_resources": ["Account XYZ at Bank ABC"],
    "reversible": true,
    "estimated_impact": "Will create a new view",
    "similar_operations_count": 0,
    "available_approval_levels": ["once", "session", "user"],
    "default_approval_level": "session"
  }
  ```

**Verification**:
```bash
# Check logs for:
grep "Requesting approval" logs/app.log
grep "approval_request" logs/app.log
```

---

### Test 2: Approve at Session Level

**Purpose**: Verify approval is saved and persisted in session state.

**Steps**:
1. Continue from Test 1
2. Send approval response:
   ```json
   {
     "approval": "approve",
     "tool_call_id": "call_xxx",
     "approval_level": "session"
   }
   ```

**Expected Behavior**:
- Graph resumes from interrupt
- `human_review_node` receives approval decision
- `ApprovalManager.save_approval()` called with:
  - `tool_name`: "obp_requests"
  - `operation`: "POST"
  - `level`: ApprovalLevel.SESSION
- State updated:
  ```python
  state["session_approvals"][("obp_requests", "POST")] = True
  state["approval_timestamps"][("obp_requests", "POST")] = datetime.now()
  ```
- Tool executes normally
- Response sent to user

**Verification**:
```bash
# Check logs:
grep "User approved tool call" logs/app.log
grep "save_approval" logs/app.log

# Check state (if you have debug endpoint):
curl http://localhost:8000/debug/state/{thread_id}
# Should show session_approvals with ("obp_requests", "POST"): true
```

---

### Test 3: Second POST Request - Uses Session Approval

**Purpose**: Verify that subsequent similar operations don't require re-approval.

**Steps**:
1. Continue same session from Test 2
2. Send another message requiring POST:
   ```
   "Create another view called 'test_view_2' for the same account"
   ```

**Expected Behavior**:
- Agent plans to use `obp_requests` with POST
- System routes to `human_review_node`
- Node checks `ToolRegistry` - POST requires approval
- Node calls `ApprovalManager.check_approval()`
- Manager finds session-level approval: `session_approvals[("obp_requests", "POST")] = True`
- Returns `"approved"` immediately
- **No interrupt() called** - continues execution
- Tool executes without user prompt
- User sees response directly

**Verification**:
```bash
# Check logs:
grep "pre-approved from persistence" logs/app.log
grep "continuing without interrupt" logs/app.log

# Should NOT see:
# "Requesting approval" (not present)
```

---

### Test 4: GET Request - Auto-Approved by Pattern

**Purpose**: Verify pattern-based auto-approval works.

**Steps**:
1. New or existing session
2. Send message requiring GET:
   ```
   "Show me all banks"
   ```

**Expected Behavior**:
- Agent plans to use `obp_requests` with GET
- System routes to `human_review_node`
- Node checks `ToolRegistry.should_require_approval()`
- Finds pattern match:
  ```python
  ApprovalPattern(method="GET", path="*", action=AUTO_APPROVE)
  ```
- Returns False (no approval needed)
- **Node returns immediately without checking ApprovalManager**
- Tool executes directly via `tools` node
- User sees response

**Verification**:
```bash
# Check logs:
grep "auto-approved by pattern" logs/app.log

# Should NOT see human_review_node called at all
# Check routing:
grep "routing decision" logs/app.log  # Should go directly to tools
```

---

### Test 5: DELETE Request - Always Denied

**Purpose**: Verify always-deny patterns work.

**Steps**:
1. Any session with OBP_API_MODE=DANGEROUS
2. Send message:
   ```
   "Delete bank ABC"
   ```

**Expected Behavior**:
- Agent plans DELETE request to `/obp/*/banks/ABC`
- System routes to `human_review_node`
- Node checks `ToolRegistry.should_require_approval()`
- Finds pattern match:
  ```python
  ApprovalPattern(method="DELETE", path="/obp/*/banks/*", action=ALWAYS_DENY)
  ```
- Returns "denied" immediately
- Node injects `ToolMessage` with denial:
  ```python
  ToolMessage(
    content="This operation is not allowed: Cannot delete banks",
    tool_call_id=tool_call_id
  )
  ```
- **No interrupt** - just denies and continues
- Agent sees denial message and responds to user accordingly

**Verification**:
```bash
# Check logs:
grep "pre-denied from persistence" logs/app.log
grep "Cannot delete banks" logs/app.log
```

---

### Test 6: Batch Approval

**Purpose**: Test multiple tool calls requiring approval simultaneously.

**Steps**:
1. Send a message that requires multiple POST operations:
   ```
   "Create three views: view1, view2, and view3 for account XYZ"
   ```

**Expected Behavior**:
- Agent plans multiple POST requests
- All tool calls routed to `human_review_node`
- Node collects all pending approvals
- Calls `interrupt()` with batch payload:
  ```json
  {
    "approval_type": "batch",
    "tool_calls": [
      {/* approval context 1 */},
      {/* approval context 2 */},
      {/* approval context 3 */}
    ],
    "options": ["approve_all", "deny_all", "approve_selected"]
  }
  ```
- Frontend receives `BatchApprovalRequestEvent`
- User responds with batch decision

**Verification**:
```bash
# Check logs:
grep "batch approval" logs/app.log
grep "BatchApprovalRequestEvent" logs/app.log
```

---

### Test 7: User-Level Approval (Redis)

**Purpose**: Test user-level approval persistence across sessions.

**Steps**:
1. **Session 1**: Approve a POST with `approval_level: "user"`
2. **Session 2**: Same user, different thread - trigger same POST operation

**Expected Behavior**:
- **Session 1**:
  - Approval saved to Redis:
    ```python
    key = "approval:user:{user_id}:obp_requests:POST"
    value = {"approved": true, "timestamp": "..."}
    ttl = 7 days
    ```
  
- **Session 2**:
  - `ApprovalManager.check_approval()` checks:
    1. Session state (empty for new session) ❌
    2. Redis user-level ✅ **Found!**
  - Returns "approved" without prompting
  - Tool executes

**Verification**:
```bash
# Check Redis:
redis-cli
> KEYS approval:user:*
> GET approval:user:{user_id}:obp_requests:POST

# Check logs:
grep "user-level approval found" logs/app.log
```

---

### Test 8: Anonymous Session Restrictions

**Purpose**: Verify anonymous sessions respect mode restrictions.

**Steps**:
1. Access without authentication (anonymous session)
2. Try to trigger POST request

**Expected Behavior**:
- OpeySession detects `is_anonymous = True`
- Forces OBP_API_MODE to SAFE (even if set to DANGEROUS)
- Only GET patterns registered
- POST attempt should fail pattern match or be rejected by tool

**Verification**:
```bash
# Check logs:
grep "Anonymous session" logs/app.log
grep "Defaulting to SAFE mode" logs/app.log
```

---

### Test 9: Mode Switching

**Purpose**: Test different OBP_API_MODE behaviors.

#### Test 9a: SAFE Mode
```bash
export OBP_API_MODE=SAFE
```
- Only GET operations available
- All GET requests auto-approved
- No human_review_node involvement

#### Test 9b: TEST Mode
```bash
export OBP_API_MODE=TEST
```
- All operations available
- Everything auto-approved (even POST/DELETE)
- No interrupts

#### Test 9c: NONE Mode
```bash
export OBP_API_MODE=NONE
```
- No OBP tools registered
- Only endpoint_retrieval and glossary_retrieval available

**Verification**:
```bash
# Check tool registration:
grep "Registered.*tools" logs/app.log
grep "OBP API mode" logs/app.log
```

---

### Test 10: Workspace Config Override

**Purpose**: Test workspace-level approval configuration.

**Steps**:
1. Set workspace config:
   ```bash
   export WORKSPACE_APPROVAL_CONFIG='{
     "obp_requests": {
       "auto_approve": [
         {"method": "POST", "path": "/obp/*/accounts/*/views"}
       ]
     }
   }'
   ```

2. Restart service
3. Try POST to create view

**Expected Behavior**:
- POST to create view matches workspace config
- Auto-approved without prompt
- Other POST requests still require approval

**Verification**:
```bash
# Check logs:
grep "workspace-level approval" logs/app.log
grep "Loaded workspace approval config" logs/app.log
```

---

## Debugging Tips

### Enable Debug Logging
```python
# In run_service.py or config
logging.basicConfig(level=logging.DEBUG)
```

### Check Graph State
```python
# Add debug endpoint
@app.get("/debug/state/{thread_id}")
async def debug_state(thread_id: str, session: OpeySession = Depends(get_opey_session)):
    config = {'configurable': {'thread_id': thread_id}}
    state = await session.graph.aget_state(config)
    return {
        "values": state.values,
        "next": state.next,
        "session_approvals": state.values.get("session_approvals", {}),
        "approval_timestamps": state.values.get("approval_timestamps", {})
    }
```

### Monitor Redis
```bash
# Watch Redis keys
redis-cli MONITOR

# Check specific keys
redis-cli KEYS "approval:*"
redis-cli GET "approval:user:123:obp_requests:POST"
```

### Check Tool Registry
```python
# In Python REPL or debug endpoint
from agent.components.tools import get_tool_registry

registry = get_tool_registry()
print(registry.list_tools())
print(registry.get_approval_metadata("obp_requests"))
```

---

## Expected Log Patterns

### Successful Approval Flow
```
INFO: Entering human review node
DEBUG: Tool call requires approval: obp_requests POST
INFO: Requesting approval for 1 tool call(s)
DEBUG: Using interrupt() to pause execution
INFO: User approved tool call: call_xxx
INFO: Saving approval at session level
DEBUG: Tool executing: obp_requests
```

### Auto-Approved Flow
```
INFO: Entering human review node
DEBUG: Tool call auto-approved by pattern: obp_requests GET
INFO: Continuing without interrupt
```

### Pre-Approved Flow
```
INFO: Entering human review node
DEBUG: Checking multi-level approvals
INFO: Session-level approval found
INFO: Continuing without interrupt
```

---

## Performance Checks

- **Approval Check Latency**: < 10ms (in-memory state check)
- **Redis User Approval**: < 50ms (network roundtrip)
- **Pattern Matching**: < 1ms (simple regex/string matching)

---

## Troubleshooting

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| Approval not persisting | State not being checkpointed | Check checkpointer config |
| Redis approval not found | TTL expired or wrong key format | Check Redis keys and TTL |
| Pattern not matching | Incorrect regex or path format | Debug `_matches_pattern()` |
| Always prompting | Session approvals not in state | Check state reducer `operator.add` |
| Tool not registered | Missing `_register_*_tools()` call | Check OpeySession.__init__ |

---

## Success Criteria

✅ **All tests pass** with expected behaviors  
✅ **Logs show** correct routing decisions  
✅ **State persists** approvals across turns  
✅ **Redis stores** user-level approvals  
✅ **Patterns match** correctly (auto-approve/deny)  
✅ **No unnecessary prompts** for pre-approved operations  
✅ **Performance** meets latency requirements  

---

## Next Steps After Testing

1. **Frontend Integration**: Update UI to display rich approval context
2. **Monitoring**: Add metrics for approval rates, patterns hit, etc.
3. **Documentation**: Update user-facing docs with approval workflows
4. **Configuration**: Create admin UI for workspace approval rules
