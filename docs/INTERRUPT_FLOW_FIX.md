# Interrupt Flow Fix - How It Works Now

## Problem Identified

The original implementation misunderstood how `interrupt()` works with `astream_events()` in LangGraph.

### What We Thought
- `interrupt()` would somehow pause during streaming
- We could detect interrupts by checking `agent_state.tasks`
- The approval event would be sent during the stream

### What Actually Happens (per LangGraph docs)
1. When `interrupt()` is called in a node, it raises an exception internally
2. The graph execution stops and saves state
3. `astream_events()` completes normally
4. **After streaming ends**, the state contains `__interrupt__` key with interrupt payloads
5. You check for `__interrupt__` and send approval events
6. User resumes in a **separate request** using `Command(resume=...)`

## Fixed Implementation

### 1. `human_review_node` (nodes.py)
```python
def human_review_node(state: OpeyGraphState, config: RunnableConfig):
    # ... approval checking logic ...
    
    # Call interrupt() - this will raise an exception and pause the graph
    logger.info(f"Calling interrupt() for tool: {approval_context.tool_name}")
    user_response = interrupt(approval_context.model_dump())
    
    # This code ONLY runs after graph is resumed with Command(resume=...)
    logger.info(f"Interrupt returned with user response: {user_response}")
    
    # Process the user_response and update state
    # ...
```

**Key points:**
- `interrupt()` raises an exception that stops execution
- Code after `interrupt()` only runs when graph is resumed
- The node will be **re-executed from the beginning** when resumed

### 2. `StreamManager._handle_approval()` (stream_manager.py)

```python
async def _handle_approval(self, config: RunnableConfig):
    # After astream_events() completes, check state for __interrupt__
    agent_state = await self.graph.aget_state(config)
    
    # According to LangGraph docs, interrupts appear here
    interrupts = agent_state.values.get("__interrupt__")
    
    if not interrupts:
        return  # No approval needed
    
    # Process each interrupt and send approval events to frontend
    for interrupt_obj in interrupts:
        approval_payload = interrupt_obj.value
        yield StreamEventFactory.approval_request(...)
```

**Key points:**
- Check `agent_state.values["__interrupt__"]` AFTER streaming completes
- This is a list of `Interrupt` objects
- Each has a `.value` containing the payload passed to `interrupt()`

### 3. Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ REQUEST 1: Initial Stream                                   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
            POST /stream {"message": "create bank"}
                           │
                           ▼
            ┌──────────────────────────┐
            │  graph.astream_events()  │
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  Nodes execute...        │
            │  → human_review_node     │
            │    → interrupt() called  │
            │    → Exception raised!   │
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  Stream completes        │
            │  State saved with        │
            │  __interrupt__           │
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  Check aget_state()      │
            │  Find __interrupt__      │
            │  Send approval_request   │
            │  event to frontend       │
            └──────────────────────────┘
                           │
                           ▼
            Frontend receives: event: approve_tool
                               data: {...approval_context...}

┌─────────────────────────────────────────────────────────────┐
│ REQUEST 2: Resume After Approval                            │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
    POST /stream {"tool_call_approval": {
                    "tool_call_id": "...",
                    "approval": "approve",
                    "approval_level": "session"
                  }}
                           │
                           ▼
            ┌──────────────────────────┐
            │  graph.astream_events()  │
            │  with Command(resume=...) │
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  human_review_node       │
            │  RE-EXECUTES from start  │
            │  This time interrupt()   │
            │  RETURNS the user value  │
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  Save approval to        │
            │  session/user/workspace  │
            │  Continue execution      │
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  Tool executes           │
            │  Response returned       │
            └──────────────────────────┘
```

## How to Resume (TODO: Update service.py)

Currently, the `/stream` endpoint handles `tool_call_approval` by injecting a `ToolMessage`. We need to update it to use `Command(resume=...)` instead:

```python
# CURRENT (WRONG):
if stream_input.tool_call_approval:
    approved = stream_input.tool_call_approval.approval == "approve"
    # ... inject ToolMessage ...

# SHOULD BE:
if stream_input.tool_call_approval:
    approved = stream_input.tool_call_approval.approval == "approve"
    approval_level = stream_input.tool_call_approval.approval_level or "once"
    
    # Create resume value that human_review_node expects
    resume_value = {
        "approved": approved,
        "approval_level": approval_level,
        "feedback": stream_input.tool_call_approval.get("feedback", "")
    }
    
    # Use Command to resume the graph
    from langgraph.types import Command
    graph_input = Command(resume=resume_value)
```

## Testing Checklist

- [x] Fixed `_handle_approval()` to check `agent_state.values["__interrupt__"]`
- [x] Added better logging in `human_review_node`
- [ ] Update `/stream` endpoint to use `Command(resume=...)` for approvals
- [ ] Test: POST request triggers interrupt → approval event sent
- [ ] Test: Approval response resumes graph correctly
- [ ] Test: Denial response injects ToolMessage correctly
- [ ] Test: Session-level approval persists
- [ ] Test: User-level approval persists across sessions

## Next Steps

1. **Restart the server** with the fixed code
2. **Test the interrupt detection** - should see `__interrupt__` in logs
3. **Update service.py** to properly resume with `Command(resume=...)`
4. **Test end-to-end** approval flow
