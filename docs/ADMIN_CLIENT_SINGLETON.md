# Admin OBP Client Singleton

## Overview

The admin OBP client singleton provides a centralized, application-wide authenticated OBP client for administrative operations. It initializes once during app startup and provides access to the admin client throughout the application lifecycle.

## Architecture

### Singleton Pattern
The `AdminClientManager` implements a thread-safe singleton pattern ensuring:
- Only one admin authentication occurs per application lifecycle
- Consistent token usage across all admin operations
- Centralized resource management

### Initialization Flow

```
App Startup → lifespan() → initialize_admin_client() → AdminClientManager.initialize()
    ↓
Validate Environment Variables
    ↓
Create DirectLogin Auth
    ↓
Verify Authentication
    ↓
Check Entitlements (optional)
    ↓
Create OBPClient
    ↓
Store in Singleton
```

## Required Environment Variables

```bash
OBP_ADMIN_USERNAME=admin_user          # Admin user's username
OBP_ADMIN_PASSWORD=secure_password     # Admin user's password
OBP_CONSUMER_KEY=your_consumer_key     # OBP consumer key
OBP_BASE_URL=https://api.openbankproject.com  # OBP API base URL
OBP_API_VERSION=v6.0.0                 # Optional, defaults to v6.0.0
```

## Setup

### 1. Configure Environment

Add the required environment variables to your `.env` file:

```bash
# Admin credentials for system operations
OBP_ADMIN_USERNAME=admin@example.com
OBP_ADMIN_PASSWORD=your_secure_password
OBP_CONSUMER_KEY=your_consumer_key
OBP_BASE_URL=https://apisandbox.openbankproject.com
```

### 2. Automatic Initialization

The admin client is automatically initialized during FastAPI app startup via the `lifespan` context manager in `service.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ... other startup code ...
    
    # Initialize admin OBP client
    try:
        await initialize_admin_client(verify_entitlements=True)
    except Exception as e:
        logger.error(f'Failed to initialize admin client: {e}')
        logger.warning('⚠️  Admin client initialization failed')
    
    yield
    
    # Cleanup
    await close_admin_client()
```

### 3. Manual Initialization (for testing)

```python
from auth import initialize_admin_client, close_admin_client

# Initialize with custom entitlements
await initialize_admin_client(
    required_entitlements=['CanCreateBank', 'CanDeleteBank'],
    verify_entitlements=True
)

# ... use admin client ...

# Clean up
await close_admin_client()
```

## Usage

### Basic Usage

```python
from auth import get_admin_client

async def create_system_user(user_data: dict):
    # Get the singleton admin client
    admin_client = get_admin_client()
    
    # Use it for admin operations
    response = await admin_client.async_obp_requests(
        "POST",
        "/obp/v6.0.0/users",
        json.dumps(user_data)
    )
    
    return response
```

### Check Initialization Status

```python
from auth import is_admin_client_initialized, get_admin_client

async def admin_operation():
    if not is_admin_client_initialized():
        raise HTTPException(
            status_code=503,
            detail="Admin operations unavailable"
        )
    
    admin_client = get_admin_client()
    # ... perform operation ...
```

### FastAPI Dependency Injection

```python
from fastapi import Depends, HTTPException
from auth import get_admin_client, is_admin_client_initialized

def require_admin_client():
    """Dependency that ensures admin client is available."""
    if not is_admin_client_initialized():
        raise HTTPException(
            status_code=503, 
            detail="Admin operations unavailable"
        )
    return get_admin_client()

@app.post("/admin/create-bank")
async def create_bank(
    bank_data: dict,
    admin_client = Depends(require_admin_client)
):
    response = await admin_client.async_obp_requests(
        "POST",
        "/obp/v6.0.0/banks",
        json.dumps(bank_data)
    )
    return response
```

### Error Handling

```python
from auth import get_admin_client

async def safe_admin_call():
    try:
        admin_client = get_admin_client()
    except RuntimeError as e:
        # Client not initialized
        logger.error(f"Admin client unavailable: {e}")
        return {"error": "Service temporarily unavailable"}
    
    try:
        response = await admin_client.async_obp_requests(
            "GET",
            "/obp/v6.0.0/banks",
            ""
        )
        return json.loads(response)
    except Exception as e:
        logger.error(f"Admin operation failed: {e}")
        return {"error": "Operation failed"}
```

## API Reference

### `initialize_admin_client(required_entitlements=None, verify_entitlements=True)`

Initialize the admin OBP client singleton.

**Parameters:**
- `required_entitlements` (list[str], optional): List of required role names to verify
- `verify_entitlements` (bool): Whether to verify admin entitlements (default: True)

**Raises:**
- `ValueError`: If required environment variables are missing or authentication fails

**Example:**
```python
await initialize_admin_client(
    required_entitlements=['CanCreateUser', 'CanGetAnyUser'],
    verify_entitlements=True
)
```

### `get_admin_client() -> OBPClient`

Get the singleton admin OBP client instance.

**Returns:**
- `OBPClient`: The initialized admin OBP client

**Raises:**
- `RuntimeError`: If the client hasn't been initialized

**Example:**
```python
admin_client = get_admin_client()
response = await admin_client.async_obp_requests("GET", "/obp/v6.0.0/banks", "")
```

### `get_admin_auth() -> OBPDirectLoginAuth`

Get the admin authentication instance.

**Returns:**
- `OBPDirectLoginAuth`: The admin authentication instance

**Raises:**
- `RuntimeError`: If the client hasn't been initialized

### `is_admin_client_initialized() -> bool`

Check if the admin client is initialized.

**Returns:**
- `bool`: True if initialized, False otherwise

### `close_admin_client()`

Close the admin client and clean up resources. Call during app shutdown.

## Default Entitlements

When `verify_entitlements=True` and no custom entitlements are provided, the system checks for these default entitlements:

- `CanCreateNonPersonalUserAttribute`
- `CanGetNonPersonalUserAttributes`
- `CanCreateSystemLevelDynamicEntity`
- `CanGetSystemLevelDynamicEntities`

These cover common administrative operations like user management and dynamic entity handling.

## Best Practices

### 1. Always Check Initialization

```python
if not is_admin_client_initialized():
    # Handle gracefully
    return fallback_behavior()
```

### 2. Use Dependency Injection for Endpoints

```python
def require_admin():
    if not is_admin_client_initialized():
        raise HTTPException(503, "Admin unavailable")
    return get_admin_client()

@app.post("/admin/action")
async def admin_action(client = Depends(require_admin)):
    # ...
```

### 3. Handle Initialization Failures Gracefully

The app continues startup even if admin initialization fails. Check availability before use:

```python
async def optional_admin_operation():
    if not is_admin_client_initialized():
        logger.warning("Admin client not available, skipping operation")
        return
    
    admin_client = get_admin_client()
    # ... perform operation ...
```

### 4. Don't Create Multiple Admin Clients

```python
# ❌ DON'T
admin_client = OBPClient(auth=OBPDirectLoginAuth(...))

# ✅ DO
admin_client = get_admin_client()
```

## Troubleshooting

### Admin Client Not Initialized

**Error:** `RuntimeError: Admin client not initialized`

**Solution:**
1. Check environment variables are set correctly
2. Check server logs for initialization errors during startup
3. Verify admin credentials are valid

### Missing Environment Variables

**Error:** `ValueError: Missing required environment variables: OBP_ADMIN_USERNAME, ...`

**Solution:**
Add missing variables to your `.env` file:
```bash
OBP_ADMIN_USERNAME=your_admin_user
OBP_ADMIN_PASSWORD=your_password
```

### Authentication Failed

**Error:** `ValueError: Failed to authenticate admin user`

**Solution:**
1. Verify credentials are correct
2. Check OBP_BASE_URL is accessible
3. Verify the admin user exists in OBP
4. Check OBP_CONSUMER_KEY is valid

### Missing Entitlements

**Warning:** `Admin user is missing required entitlements: ...`

This is a warning, not an error. The admin client still initializes but may not be able to perform certain operations.

**Solution:**
Grant the required entitlements to the admin user in OBP, or disable entitlement verification:
```python
await initialize_admin_client(verify_entitlements=False)
```

## Testing

Run the test suite:

```bash
pytest test/auth/test_admin_client.py -v
```

For integration testing with a real OBP instance, ensure test environment variables are configured.

## Related Documentation

- [Direct Login Authentication](../src/auth/auth.py)
- [OBP Client](../src/client/obp_client.py)
- [Service Startup](../src/service/service.py)
