# OBP Checkpoint Saver Architecture

## Overview

The `OBPCheckpointSaver` uses OBP Dynamic Entities as a storage backend for LangGraph checkpoints. It follows a dual-client architecture to separate admin operations from user operations, while maintaining JSON-serializability of the RunnableConfig.

## Architecture

### Two-Client Pattern with JSON-Serializable Config

1. **Admin Client** (Setup Phase)
   - Used **only** during `setup()` to create system-level dynamic entities
   - Creates the `OpeyCheckpoint` and `OpeyCheckpointWrite` entity schemas
   - Requires admin privileges to access `/obp/v6.0.0/management/system-dynamic-entities`
   - Called once at application startup

2. **User Client** (CRUD Operations)
   - **Reconstructed** from `consent_id` stored in `config['configurable']['consent_id']`
   - Each user accesses their own CRUD endpoints at `/obp/v6.0.0/my/dynamic-entities/`
   - Uses the user's authentication credentials via OBPConsentAuth
   - No admin privileges required
   - **consent_id is JSON-serializable** (required by LangGraph)

### Why This Separation?

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Startup                       │
│                                                               │
│  1. OBPCheckpointSaver() initialization (stateless)          │
│  2. await saver.setup()  ──►  Uses Admin Client              │
│     - Check if entities exist                                │
│     - Create system entities if needed                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Runtime Operations                        │
│                                                               │
│  User Session:                                               │
│    config = {                                                │
│      "configurable": {                                       │
│        "thread_id": "thread-1",                              │
│        "consent_id": "consent-abc123"  ◄── JSON-serializable │
│      }                                                       │
│    }                                                         │
│                                                              │
│  await graph.ainvoke(input, config)                          │
│    └─► OBPClient created from consent_id                    │
│        Checkpoints saved to /obp/v6.0.0/my/dynamic-entities/ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Details

### Initialization

```python
# Global checkpointer - stateless, no client stored
checkpointer = OBPCheckpointSaver()
await checkpointer.setup()  # Uses admin client internally
```

### OpeySession Integration

The `OpeySession.build_config()` method automatically injects the user's `consent_id` into the config:

```python
def build_config(self, base_config: dict | None = None) -> dict:
    session_configurable = {
        "model_name": self._model_name,
        "approval_manager": self.approval_manager,
    }
    
    # Add consent_id for checkpoint operations (JSON-serializable)
    if not self.is_anonymous and self.consent_id:
        session_configurable["consent_id"] = self.consent_id
    
    # Merge with base config
    merged_configurable = {
        **session_configurable,
        **base_config.get("configurable", {})
    }
    
    return {"configurable": merged_configurable}
```

### CRUD Operations

All checkpoint CRUD operations create an OBPClient from the consent_id in config:

```python
def _get_client_from_config(self, config: RunnableConfig) -> OBPClient:
    """Create an OBPClient from the consent_id in config."""
    from src.auth.auth import OBPConsentAuth
    
    consent_id = config.get("configurable", {}).get("consent_id")
    
    # Create auth and client from consent_id
    auth = OBPConsentAuth(consent_id=consent_id)
    return OBPClient(auth)

async def aget_tuple(self, config: RunnableConfig):
    client = self._get_client_from_config(config)  # Creates OBPClient
    # Use client for user-specific CRUD operations
    endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointEntity.obp_entity_name()}"
    response = await client.get(endpoint)
    ...
```

## Dynamic Entity Endpoints

### System-Level (Admin Only)

- `POST /obp/v6.0.0/management/system-dynamic-entities` - Create entity schemas
- `GET /obp/v6.0.0/management/system-dynamic-entities` - List entity schemas

### User-Level (Per-User CRUD)

Once entities are created, each user gets their own endpoints:

- `GET /obp/v6.0.0/my/dynamic-entities/OpeyCheckpoint` - List user's checkpoints
- `POST /obp/v6.0.0/my/dynamic-entities/OpeyCheckpoint` - Create checkpoint
- `GET /obp/v6.0.0/my/dynamic-entities/OpeyCheckpointWrite` - List user's writes
- `POST /obp/v6.0.0/my/dynamic-entities/OpeyCheckpointWrite` - Create write

## Security Model

1. **System entities are shared** - All users use the same entity schemas
2. **Data is isolated** - Each user only accesses their own checkpoint data
3. **No privilege escalation** - Users cannot access admin endpoints
4. **Authentication enforced** - User's consent JWT required for CRUD operations

## Anonymous Sessions

For anonymous sessions:
- Checkpoints are **disabled** (no OBP client available)
- Graph runs without checkpoint persistence
- Session state is ephemeral

## Error Handling

### Missing Admin Client (Setup)

```python
async def setup(self):
    try:
        admin_client = get_admin_client()
    except RuntimeError as e:
        raise ValueError(
            "Admin client must be initialized for checkpoint saver setup. "
            "This is required to create system-level dynamic entities."
        ) from e
```

### Missing consent_id (Runtime)

```python
def _get_client_from_config(self, config):
    consent_id = config.get("configurable", {}).get("consent_id")
    if not consent_id:
        raise ValueError(
            "consent_id must be provided in config['configurable']['consent_id']. "
            "This is required to create an authenticated OBPClient for checkpoint CRUD operations."
        )
    # Create OBPClient from consent_id
    auth = OBPConsentAuth(consent_id=consent_id)
    return OBPClient(auth)
```

## Benefits

1. **Separation of Concerns**: Admin setup vs user operations
2. **Security**: Users can't create system entities
3. **Scalability**: Each user's data is isolated
4. **Flexibility**: Different users can have different permissions
5. **Testability**: Easy to mock user/admin clients separately
6. **JSON-Serializable**: RunnableConfig only contains primitive types (required by LangGraph)

## Testing

```python
# Test setup
admin_client = Mock(OBPClient)

# Test initialization
saver = OBPCheckpointSaver()
with patch('get_admin_client', return_value=admin_client):
    await saver.setup()

# Test CRUD operations - use consent_id instead of client object
config = {
    "configurable": {
        "thread_id": "test-thread",
        "consent_id": "test-consent-123"  # JSON-serializable!
    }
}
await saver.aget_tuple(config)  # Uses user_client
```
