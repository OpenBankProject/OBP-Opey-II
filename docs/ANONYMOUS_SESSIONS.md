# Anonymous Sessions

This document describes the anonymous session feature in OBP-Opey-II, which allows users to interact with the system without requiring OBP authentication, subject to usage limits.

## Overview

Anonymous sessions provide a way for users to try out Opey without needing to authenticate with the Open Bank Project (OBP) API. These sessions are rate-limited to prevent abuse while still allowing meaningful exploration of the system's capabilities.

## Configuration

Anonymous sessions are controlled by environment variables in your `.env` file:

```bash
# Enable/disable anonymous sessions
ALLOW_ANONYMOUS_SESSIONS="true"

# Maximum tokens an anonymous session can consume
ANONYMOUS_SESSION_TOKEN_LIMIT=10000

# Maximum requests an anonymous session can make
ANONYMOUS_SESSION_REQUEST_LIMIT=20
```

## Features

### Session Types

1. **Authenticated Sessions**: Created with valid OBP Consent-JWT, have unlimited usage
2. **Anonymous Sessions**: Created without authentication, subject to usage limits

### Usage Tracking

Anonymous sessions track two metrics:
- **Token Usage**: Estimated tokens consumed by LLM interactions
- **Request Count**: Number of API requests made to Opey

### Rate Limiting

When anonymous sessions exceed their limits, they receive HTTP 429 responses with detailed usage information and instructions to authenticate.

### Restricted Functionality

Anonymous sessions have limited access to OBP API features:
- Only basic retrieval tools (glossary and endpoint search) are available
- Direct OBP API calls are disabled regardless of `OBP_API_MODE` setting
- Sessions are automatically downgraded to `SAFE` mode if configured otherwise

## API Endpoints

### Create Session

#### Anonymous Session
```http
POST /create-session
```

Creates an anonymous session when no `Consent-JWT` header is provided.

**Response:**
```json
{
  "message": "Anonymous session created",
  "session_type": "anonymous",
  "usage_limits": {
    "token_limit": 10000,
    "request_limit": 20
  }
}
```

#### Authenticated Session
```http
POST /create-session
Consent-JWT: <valid-jwt-token>
```

Creates an authenticated session with unlimited usage.

### Check Usage

```http
GET /usage
Cookie: session=<session-id>
```

Returns detailed usage information:

```json
{
  "session_type": "anonymous",
  "tokens_used": 1250,
  "token_limit": 10000,
  "tokens_remaining": 8750,
  "requests_made": 5,
  "request_limit": 20,
  "requests_remaining": 15,
  "approaching_token_limit": false,
  "approaching_request_limit": false
}
```

### Upgrade Session

```http
POST /upgrade-session
Cookie: session=<session-id>
Consent-JWT: <valid-jwt-token>
```

Upgrades an anonymous session to authenticated, preserving usage history:

```json
{
  "message": "Session successfully upgraded to authenticated",
  "session_type": "authenticated",
  "previous_usage": {
    "tokens_used": 1250,
    "requests_made": 5
  }
}
```

### Status Check

```http
GET /status
Cookie: session=<session-id>
```

Returns system status with usage information:

```json
{
  "status": "ok",
  "usage": {
    "session_type": "anonymous",
    "tokens_used": 1250,
    "token_limit": 10000,
    // ... other usage fields
  }
}
```

## Error Handling

### Rate Limit Exceeded

When limits are exceeded, the API returns HTTP 429:

```json
{
  "error": "Token limit exceeded",
  "message": "Anonymous sessions are limited to 10000 tokens. Please authenticate to continue.",
  "usage": {
    "tokens_used": 10000,
    "token_limit": 10000,
    "requests_made": 15,
    "request_limit": 20
  }
}
```

### Anonymous Sessions Disabled

When `ALLOW_ANONYMOUS_SESSIONS=false`, requests without authentication return HTTP 401:

```
Missing Authorization headers, Must be one of ['Consent-JWT']
```

## Implementation Details

### Session Data Structure

```python
class SessionData(BaseModel):
    consent_jwt: Optional[str] = None
    is_anonymous: bool = False
    token_usage: int = 0
    request_count: int = 0
```

### Usage Tracking

- Token usage is estimated during streaming responses
- Request count is incremented on each `/invoke` or `/stream` call
- Usage data is persisted in the session backend
- Limits are checked before processing requests

### Security Considerations

1. **Rate Limiting**: Prevents abuse of anonymous access
2. **Feature Restrictions**: Anonymous sessions can't access sensitive OBP operations
3. **Session Isolation**: Each anonymous session is independent
4. **Upgrade Path**: Clear path to authenticate for full access

## Usage Examples

### Python Client

```python
from client import AgentClient

# Create client (will use anonymous session if no auth provided)
client = AgentClient("http://localhost:5000")

# Make requests until rate limited
try:
    response = client.invoke("Tell me about OBP APIs")
    print(response.content)
except Exception as e:
    if "429" in str(e):
        print("Rate limited - please authenticate")
```

### JavaScript/Frontend

```javascript
// Create anonymous session
const response = await fetch('/create-session', {
  method: 'POST',
  credentials: 'include'
});

const sessionInfo = await response.json();
console.log('Session created:', sessionInfo);

// Check usage
const usage = await fetch('/usage', {
  credentials: 'include'
}).then(r => r.json());

console.log('Current usage:', usage);
```

## Best Practices

1. **Monitor Usage**: Check usage regularly to inform users about remaining capacity
2. **Graceful Degradation**: Handle rate limit errors gracefully in your UI
3. **Encourage Authentication**: Provide clear upgrade paths for users hitting limits
4. **Set Reasonable Limits**: Balance user experience with resource protection

## Troubleshooting

### Common Issues

1. **Session not persisting**: Ensure cookies are enabled and HTTPS is used in production
2. **Usage not updating**: Check that middleware is properly configured
3. **Rate limits too restrictive**: Adjust `ANONYMOUS_SESSION_*_LIMIT` values

### Logging

Anonymous session activity is logged at INFO level:
```
Creating anonymous session
Anonymous session token usage: 1250/10000
Anonymous session exceeded token limit: 10000/10000
```

## Migration Guide

### Enabling Anonymous Sessions

1. Set `ALLOW_ANONYMOUS_SESSIONS="true"` in `.env`
2. Configure appropriate limits for your use case
3. Update client applications to handle 429 responses
4. Test the upgrade flow with valid OBP credentials

### Disabling Anonymous Sessions

1. Set `ALLOW_ANONYMOUS_SESSIONS="false"` in `.env`
2. Ensure all client applications provide valid authentication
3. Remove anonymous session handling from frontend code