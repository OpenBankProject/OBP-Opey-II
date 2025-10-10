# Approval System: Config Pattern (Recommended)

## Overview

The approval system uses LangGraph's **config pattern** to pass non-serializable objects like `ApprovalManager` to nodes. This avoids the antipattern of storing non-serializable objects in the graph state.

## Architecture

### What Goes Where

| Component | Storage Location | Reason |
|-----------|-----------------|--------|
| **ApprovalManager instance** | Graph config (`configurable`) | Non-serializable, per-session |
| **ToolRegistry instance** | Singleton (global) | Shared across all sessions |
| **session_approvals** | Graph state | Serializable, persisted by checkpointer |
| **approval_timestamps** | Graph state | Serializable, persisted by checkpointer |

### Pattern Summary

```python
# ✅ CORRECT: Non-serializable objects via config
config = {
    'configurable': {
        'thread_id': thread_id,
        'approval_manager': approval_manager  # Pass here
    }
}
graph.astream(state, config)

# ❌ WRONG: Non-serializable objects in state (antipattern)
state = {
    'messages': [...],
    'approval_manager': approval_manager  # Don't do this!
}
```

## Implementation

### 1. OpeySession: Create and Store ApprovalManager

```python
class OpeySession:
    def __init__(self, ...):
        # Create per-session ApprovalManager
        redis_client = get_redis_client() if os.getenv("REDIS_URL") else None
        workspace_config = self._load_workspace_approval_config()
        self.approval_manager = create_approval_manager(
            redis_client=redis_client,
            workspace_config=workspace_config
        )
        
        # Store as instance variable (NOT in state)
        # Will be passed via config when streaming
```

### 2. StreamManager: Pass via Config

When invoking the graph, pass the `approval_manager` via the config:

```python
# In StreamManager._stream method
async for event in self.session.graph.astream(
    user_message_dict,
    config={
        "configurable": {
            "thread_id": str(self.thread_id),
            "approval_manager": self.session.approval_manager  # ✅ Pass here
        }
    },
    stream_mode="messages"
):
    # Handle events...
```

### 3. Nodes: Access from Config

Nodes that need the `ApprovalManager` accept a `config` parameter:

```python
from langchain_core.runnables import RunnableConfig

async def human_review_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Node that uses ApprovalManager from config.
    
    Args:
        state: Graph state (serializable data only)
        config: RunnableConfig with approval_manager in configurable section
    """
    # Get approval_manager from config
    configurable = config.get("configurable", {}) if config else {}
    approval_manager = configurable.get("approval_manager")
    
    if not approval_manager:
        logger.warning("No approval_manager in config")
        return state
    
    # Use approval_manager
    approval_status = await approval_manager.check_approval(...)
    # ...
```

### 4. Graph State: Only Serializable Data

```python
class OpeyGraphState(MessagesState):
    """
    State contains ONLY serializable data that can be persisted.
    """
    conversation_summary: str
    current_state: str
    total_tokens: int
    
    # ✅ Serializable: approval tracking
    session_approvals: Annotated[Dict[Tuple[str, str], bool], operator.add]
    approval_timestamps: Annotated[Dict[Tuple[str, str], datetime], operator.add]
    
    # ❌ Do NOT add non-serializable objects:
    # approval_manager: ApprovalManager  # ANTIPATTERN!
```

## Complete Flow

### Initialization (OpeySession.__init__)

```
1. Create approval_manager instance
   ↓
2. Store as self.approval_manager
   ↓
3. Register tools with ToolRegistry (singleton)
   ↓
4. Build graph (no approval_manager reference)
```

### Request Handling (StreamManager)

```
1. User sends message
   ↓
2. StreamManager calls graph.astream()
   ↓
3. Pass approval_manager via config['configurable']
   ↓
4. Graph executes, nodes access via config
   ↓
5. Checkpointer persists state (NOT approval_manager)
```

### Approval Flow (human_review_node)

```
1. Node receives state + config
   ↓
2. Extract approval_manager from config
   ↓
3. Check for pre-existing approvals
   ↓
4. If needed, use interrupt() for new approval
   ↓
5. Save approval decision to state (serializable)
   ↓
6. State persisted by checkpointer
```

## Benefits of Config Pattern

### ✅ Advantages

1. **Serialization**: State can be checkpointed without issues
2. **Separation of Concerns**: Data vs. behavior clearly separated
3. **LangGraph Best Practice**: Follows recommended patterns
4. **Per-Session Isolation**: Each session has its own manager
5. **No Circular Dependencies**: Config injected at runtime

### ❌ Antipattern to Avoid

```python
# DON'T store non-serializable objects in state
class OpeyGraphState(MessagesState):
    approval_manager: ApprovalManager  # ❌ WRONG!
    redis_client: Redis  # ❌ WRONG!
    session: OpeySession  # ❌ WRONG!
```

**Why it's bad:**
- Checkpointer can't serialize these objects
- State becomes coupled to runtime instances
- Breaks graph resume/replay functionality
- Violates LangGraph design principles

## Passing Multiple Runtime Objects

If you need to pass multiple objects:

```python
config = {
    'configurable': {
        'thread_id': thread_id,
        'approval_manager': approval_manager,
        'redis_client': redis_client,
        'user_id': user_id,
        # Add any other runtime objects here
    }
}
```

Access in nodes:

```python
async def my_node(state: OpeyGraphState, config: RunnableConfig):
    configurable = config.get("configurable", {})
    
    approval_manager = configurable.get("approval_manager")
    redis_client = configurable.get("redis_client")
    user_id = configurable.get("user_id")
    
    # Use them...
```

## Testing

When testing nodes, pass a mock config:

```python
async def test_human_review_node():
    # Create mock approval manager
    mock_approval_manager = MockApprovalManager()
    
    # Create test config
    config = RunnableConfig(configurable={
        'approval_manager': mock_approval_manager
    })
    
    # Test node
    result = await human_review_node(test_state, config)
    assert result == expected_result
```

## Summary

- **ToolRegistry**: Singleton, app-level, shared across sessions
- **ApprovalManager**: Per-session instance, passed via config
- **Graph State**: Only serializable data (approvals, timestamps)
- **Config Pattern**: Pass runtime objects via `config['configurable']`
- **Nodes**: Accept `config: RunnableConfig` parameter to access objects

This pattern ensures clean separation, proper serialization, and follows LangGraph best practices.
