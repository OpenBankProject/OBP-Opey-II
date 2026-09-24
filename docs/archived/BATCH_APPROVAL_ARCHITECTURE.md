> ### ⚠️ OUT OF DATE — describes a system that does not run
>
> *Annotated 2026-09-22. This note was added to an existing document; no code and no other
> part of this document was changed.*
>
> The human-in-the-loop tool-approval system described below **is not active**. All five
> `OBP_API_MODE` branches in `src/service/opey_session.py` (lines 163, 177, 187, 198, 211)
> build the graph with `.enable_human_review(False)`, so `human_review_node` is never added
> to it and `ApprovalStore` is never consulted. `create_supervised_opey_graph`
> (`src/agent/graph_builder.py:460`) is the only caller that passes `True`, and nothing calls it.
>
> **Authorization is handled by the OBP consent flow instead** — `consent_check_node`
> (`src/agent/components/nodes.py:642`) plus the roles carried by the consent JWT, enforced
> server-side by OBP. See `../../CONSENT_FLOW.md`. This is deliberate: the `DANGEROUS` branch
> carries the comment `# Consent flow handles authorization`.
>
> **Note:** unlike the other documents in this set, the batch logic described below *does*
> still exist in `human_review_node` — it is simply never reached.
>
> **Latent bug, if human review is ever re-enabled:** `human_review_node` computes
> `approved_ids` from `_process_approval_response` and then discards it, and the edge to the
> tools node is unconditional. LangGraph's `ToolNode._parse_input`
> (`langgraph/prebuilt/tool_node.py:1228`) selects its work with
> `next(m for m in reversed(messages) if isinstance(m, AIMessage))`, walking back past the
> denial `ToolMessage` to the AIMessage and executing **every** tool call on it. A denied tool
> call would therefore run anyway, leaving two ToolMessages sharing one `tool_call_id`. This
> applies to partial denial and to denying everything. Not a live risk while the node is
> unreachable; it must be fixed before the flag is turned on.
>
> Kept for historical reference. Do not follow it as a guide to current behaviour.

---

# Batch Approval Architecture - Before vs After

## The Problem: Race Conditions with Parallel Tool Calls

### Before (Problematic)

```
LLM Response: AIMessage(tool_calls=[call_1, call_2, call_3])
                              ↓
                    human_review_node LOOPS
                              ↓
                    ┌─────────┴─────────┐
                    ↓                   ↓
            FOR tool_call_1     FOR tool_call_2     FOR tool_call_3
                    ↓                   ↓                   ↓
             interrupt(ctx_1)    interrupt(ctx_2)    interrupt(ctx_3)
                    ↓                   ↓                   ↓
              Graph suspends     Graph suspends     Graph suspends
                    ↓                   ↓                   ↓
         SSE: approval_req_1  SSE: approval_req_2  SSE: approval_req_3
                    ↓                   ↓                   ↓
              Frontend UI      Frontend UI        Frontend UI
                    ↓                   ↓                   ↓
         POST /stream (1)    POST /stream (2)    POST /stream (3)
                    ↓                   ↓                   ↓
            ⚠️  RACE CONDITION - Multiple streams may overlap!
```

**Issues:**
- Multiple `interrupt()` calls = Multiple suspend/resume cycles
- If user clicks fast, streams can overlap
- Same thread_id processed concurrently
- State updates can interleave
- Orchestrator confusion

---

### After (Fixed)

```
LLM Response: AIMessage(tool_calls=[call_1, call_2, call_3])
                              ↓
                    human_review_node
                              ↓
                 Categorize all tool calls
                              ↓
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
   Auto-approved          Denied          Needs Approval
   [call_1]              [call_2]         [call_3, call_4]
        ↓                     ↓                     ↓
   (continue)         (create error)      Build contexts
                                                    ↓
                                          Create batch payload
                                                    ↓
                                    ┌───────────────┴───────────────┐
                                    ↓                               ↓
                            If 1 tool:                      If >1 tools:
                        interrupt(single_ctx)           interrupt(batch_ctx)
                                    ↓                               ↓
                          Graph suspends ONCE
                                    ↓
                        SSE: Single batch_approval_request
                                    ↓
                              Frontend UI
                         (Shows all approvals)
                                    ↓
                          POST /stream (batch)
                                    ↓
                           Command(resume={
                             decisions: {...}
                           })
                                    ↓
                          Graph resumes ONCE
                                    ↓
                    Process all decisions atomically
```

**Benefits:**
- ✅ ONE `interrupt()` call per approval cycle
- ✅ ONE suspend/resume cycle
- ✅ ONE stream operation
- ✅ No race conditions possible
- ✅ Atomic decision processing

---

## Code Comparison

### Before: Multiple interrupt() calls

```python
async def human_review_node(state, config):
    tool_calls = tool_call_message.tool_calls
    
    # ❌ PROBLEM: Looping with interrupt()
    for tool_call in tool_calls:
        if needs_approval(tool_call):
            context = build_context(tool_call)
            
            # Each interrupt creates a suspend/resume cycle!
            user_response = interrupt(context)  # ⚠️
            
            process_response(user_response)
```

### After: Single interrupt() with batch

```python
async def human_review_node(state, config):
    tool_calls = tool_call_message.tool_calls
    
    # ✅ SOLUTION: Collect all, interrupt once
    needs_approval = []
    for tool_call in tool_calls:
        if needs_approval(tool_call):
            needs_approval.append(tool_call)
    
    if not needs_approval:
        return {}
    
    # Build contexts for ALL tools
    contexts = [build_context(tc) for tc in needs_approval]
    
    # Single interrupt with batch payload
    if len(needs_approval) == 1:
        user_response = interrupt(contexts[0])  # ✅ Single
    else:
        user_response = interrupt({  # ✅ Batch
            "approval_type": "batch",
            "tool_calls": contexts
        })
    
    # Process all decisions together
    process_all_decisions(user_response)
```

---

## Request Flow Comparison

### Before: Sequential Approvals

```
Time  Client                    Server
────────────────────────────────────────────────────
t0    POST /stream              
      "Hello"                   → Graph starts
                                → LLM responds
                                → Tool calls: [A, B, C]
                                → interrupt(A)
t1    ← SSE: approval_req(A)    
      
t2    POST /stream              
      approve(A)                → Resume, interrupt(B)
                                
t3    ← SSE: approval_req(B)    
      
t4    POST /stream              ⚠️ If this arrives before
      approve(B)                ⚠️ t3 completes = RACE!
```

### After: Batch Approval

```
Time  Client                    Server
────────────────────────────────────────────────────
t0    POST /stream              
      "Hello"                   → Graph starts
                                → LLM responds
                                → Tool calls: [A, B, C]
                                → Collect all needing approval
                                → interrupt(BATCH)
t1    ← SSE: batch_approval_req 
         (A, B, C)              
      
t2    POST /stream              
      batch_approve({           → Resume ONCE
        A: approve,             → Process all
        B: approve,             → No race possible!
        C: deny
      })
```

---

## State Machine Comparison

### Before: Multiple State Transitions

```
State: IDLE
  ↓ (user message)
State: STREAMING
  ↓ (tool calls detected)
State: WAITING_APPROVAL_1
  ↓ (user approves A)
State: PROCESSING_APPROVAL_1
  ↓ (check next tool)
State: WAITING_APPROVAL_2  ⚠️ Can overlap with client request
  ↓ (user approves B)
State: PROCESSING_APPROVAL_2  ⚠️ Can overlap with client request
  ↓ (check next tool)
State: WAITING_APPROVAL_3
  ...
```

### After: Single State Transition

```
State: IDLE
  ↓ (user message)
State: STREAMING
  ↓ (tool calls detected)
State: WAITING_APPROVAL (all at once)
  ↓ (user responds with batch)
State: PROCESSING_APPROVAL (atomic)
  ↓ (all done)
State: STREAMING (continue)
  ↓
State: IDLE
```

---

## Performance Impact

### Before
- **Approvals needed**: 3 tools
- **interrupt() calls**: 3
- **HTTP requests**: 4 (1 initial + 3 approvals)
- **State reads**: 3
- **State writes**: 3
- **Potential races**: HIGH (3 concurrent windows)

### After
- **Approvals needed**: 3 tools
- **interrupt() calls**: 1 ✅
- **HTTP requests**: 2 (1 initial + 1 batch approval) ✅
- **State reads**: 1 ✅
- **State writes**: 1 ✅
- **Potential races**: NONE ✅

---

## Key Insight

> **The race condition wasn't about concurrent requests—it was about calling `interrupt()` multiple times in a loop, creating multiple overlapping suspend/resume cycles.**

LangGraph's parallel tool calling requires a parallel approval mechanism, not a sequential one.
