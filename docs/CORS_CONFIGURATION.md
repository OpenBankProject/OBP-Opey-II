# CORS Configuration Guide

## Overview

Cross-Origin Resource Sharing (CORS) is configured in Opey II to allow web frontends to communicate with the backend service. This guide explains how to configure CORS settings for different environments.

## Current CORS Implementation

The service automatically configures CORS middleware based on environment variables. The configuration supports:

- ✅ Multiple allowed origins
- ✅ Configurable HTTP methods
- ✅ Configurable request headers
- ✅ Credential support (cookies, authorization headers)
- ✅ Development environment fallbacks

## Environment Variables

### CORS_ALLOWED_ORIGINS

**Required for production, optional for development**

Comma-separated list of allowed origins that can make requests to the API.

```bash
# Single origin
CORS_ALLOWED_ORIGINS=http://localhost:5174

# Multiple origins
CORS_ALLOWED_ORIGINS=http://localhost:5174,http://localhost:3000,https://myapp.com

# Production example
CORS_ALLOWED_ORIGINS=https://opey-frontend.example.com,https://admin.example.com
```

**Default (development only):** If not set, defaults to common development origins:
- `http://localhost:5174` (Vite default)
- `http://localhost:3000` (React/Next.js default)
- `http://127.0.0.1:5174`
- `http://127.0.0.1:3000`

### CORS_ALLOWED_METHODS

**Optional**

Comma-separated list of HTTP methods allowed in CORS requests.

```bash
CORS_ALLOWED_METHODS=GET,POST,PUT,DELETE,OPTIONS
```

**Default:** `GET,POST,PUT,DELETE,OPTIONS`

### CORS_ALLOWED_HEADERS

**Optional**

Comma-separated list of headers that can be used in CORS requests.

```bash
CORS_ALLOWED_HEADERS=Content-Type,Authorization,Consent-JWT
```

**Default:** `Content-Type,Authorization,Consent-JWT`

## Configuration Examples

### Development Environment

For local development, you can either:

**Option 1: Use defaults (no configuration needed)**
```bash
# No CORS variables needed - uses development defaults
```

**Option 2: Explicit configuration**
```bash
CORS_ALLOWED_ORIGINS=http://localhost:5174
CORS_ALLOWED_METHODS=GET,POST,OPTIONS
CORS_ALLOWED_HEADERS=Content-Type,Authorization,Consent-JWT
```

### Production Environment

Always explicitly set CORS origins in production:

```bash
# Production CORS configuration
CORS_ALLOWED_ORIGINS=https://your-frontend-domain.com
CORS_ALLOWED_METHODS=GET,POST,PUT,DELETE,OPTIONS
CORS_ALLOWED_HEADERS=Content-Type,Authorization,Consent-JWT,X-Requested-With
```

### Multi-Environment Setup

```bash
# Staging and production
CORS_ALLOWED_ORIGINS=https://staging.myapp.com,https://myapp.com

# Include admin interfaces
CORS_ALLOWED_ORIGINS=https://app.myapp.com,https://admin.myapp.com,https://dashboard.myapp.com
```

## Security Considerations

### ✅ Do's

- Always specify exact origins in production (never use `*`)
- Use HTTPS in production origins
- Limit headers to only what's necessary
- Regularly audit allowed origins

### ❌ Don'ts

- Never use `*` as an origin in production
- Don't include `http://` origins in production HTTPS environments
- Don't allow unnecessary HTTP methods
- Don't include sensitive domains you don't control

## Testing CORS Configuration

### 1. Browser Developer Tools

Check the Network tab for CORS-related errors:

```
Access to fetch at 'http://localhost:8000/stream' from origin 'http://localhost:5174' has been blocked by CORS policy
```

### 2. Preflight Request Test

Use curl to test OPTIONS requests:

```bash
curl -X OPTIONS \
  -H "Origin: http://localhost:5174" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type,Authorization" \
  http://localhost:8000/stream
```

Expected response headers:
```
Access-Control-Allow-Origin: http://localhost:5174
Access-Control-Allow-Methods: GET,POST,PUT,DELETE,OPTIONS
Access-Control-Allow-Headers: Content-Type,Authorization,Consent-JWT
Access-Control-Allow-Credentials: true
```

### 3. Actual Request Test

```bash
curl -X POST \
  -H "Origin: http://localhost:5174" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  http://localhost:8000/stream
```

## Troubleshooting

### Common Issues

**1. "CORS policy" errors in browser**
```
Solution: Ensure your frontend origin is in CORS_ALLOWED_ORIGINS
```

**2. "Credential include" errors**
```
Solution: Verify allow_credentials=True is set (automatic in our config)
```

**3. Custom headers being blocked**
```
Solution: Add custom headers to CORS_ALLOWED_HEADERS
```

**4. Preflight requests failing**
```
Solution: Ensure OPTIONS method is in CORS_ALLOWED_METHODS
```

### Debug Logging

The service logs CORS configuration at startup:

```
INFO - CORS configured with origins: ['http://localhost:5174', 'http://localhost:3000']
```

If you see a warning:
```
WARNING - CORS_ALLOWED_ORIGINS not set, using development defaults
```

This means you're using fallback development origins.

## Integration Examples

### Frontend JavaScript

```javascript
// Fetch with credentials
fetch('http://localhost:8000/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer token',
    'Consent-JWT': 'jwt-token'
  },
  credentials: 'include', // Important for cookies
  body: JSON.stringify({message: 'Hello'})
});
```

### React/Next.js

```javascript
// In your API client
const apiClient = axios.create({
  baseURL: 'http://localhost:8000',
  withCredentials: true, // Include cookies
  headers: {
    'Content-Type': 'application/json'
  }
});
```

## Environment-Specific Configurations

### Docker Development

```dockerfile
# In docker-compose.yml
environment:
  - CORS_ALLOWED_ORIGINS=http://localhost:5174,http://host.docker.internal:5174
```

### Kubernetes Production

```yaml
# In ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: opey-config
data:
  CORS_ALLOWED_ORIGINS: "https://opey.yourdomain.com"
  CORS_ALLOWED_METHODS: "GET,POST,PUT,DELETE,OPTIONS"
  CORS_ALLOWED_HEADERS: "Content-Type,Authorization,Consent-JWT"
```

## Migration from Previous Configuration

If you're upgrading from an older version that used a single string for `CORS_ALLOWED_ORIGINS`:

**Old format:**
```bash
CORS_ALLOWED_ORIGINS=http://localhost:5174
```

**New format (backward compatible):**
```bash
CORS_ALLOWED_ORIGINS=http://localhost:5174
# or
CORS_ALLOWED_ORIGINS=http://localhost:5174,http://localhost:3000
```

The new implementation is backward compatible and will handle both single origins and comma-separated lists.