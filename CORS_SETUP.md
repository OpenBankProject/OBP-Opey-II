# CORS Configuration Summary for Opey II

## Current Status ✅

CORS is now properly configured in Opey II with the following improvements:

### ✅ What's Working
- **Multiple Origins Support**: Can handle comma-separated list of allowed origins
- **Development Fallbacks**: Automatically uses common dev origins if not configured
- **Flexible Configuration**: Separate environment variables for methods and headers
- **Security Headers**: Proper credential handling and specific header allowance
- **Debug Support**: Optional CORS debugging middleware
- **Backward Compatibility**: Works with existing single-origin configurations

## Environment Variables

### Required for Production
```bash
CORS_ALLOWED_ORIGINS=http://localhost:5174,https://your-frontend-domain.com
```

### Optional (with sensible defaults)
```bash
CORS_ALLOWED_METHODS=GET,POST,PUT,DELETE,OPTIONS
CORS_ALLOWED_HEADERS=Content-Type,Authorization,Consent-JWT
DEBUG_CORS=true  # Enable CORS debug logging
```

## Quick Setup

### For Development (Default - No Config Needed)
If you don't set `CORS_ALLOWED_ORIGINS`, the system automatically allows:
- `http://localhost:5174` (Vite/SvelteKit default)
- `http://localhost:3000` (React/Next.js default)
- `http://127.0.0.1:5174`
- `http://127.0.0.1:3000`

### For Your Specific Frontend
Add to your `.env` file:
```bash
CORS_ALLOWED_ORIGINS=http://localhost:5174
```

### For Multiple Frontends
```bash
CORS_ALLOWED_ORIGINS=http://localhost:5174,http://localhost:3000,https://staging.myapp.com
```

### For Production
```bash
CORS_ALLOWED_ORIGINS=https://your-production-domain.com
CORS_ALLOWED_METHODS=GET,POST,PUT,DELETE,OPTIONS
CORS_ALLOWED_HEADERS=Content-Type,Authorization,Consent-JWT
```

## Testing CORS

### Method 1: Use the Test Script
```bash
cd OBP-Opey-II
python scripts/test_cors.py --url http://localhost:8000
```

### Method 2: Manual Browser Test
1. Open browser dev tools
2. Try making a request from your frontend
3. Look for CORS errors in console
4. Check Network tab for proper headers

### Method 3: curl Test
```bash
# Test preflight request
curl -X OPTIONS \
  -H "Origin: http://localhost:5174" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  http://localhost:8000/status

# Should return headers like:
# Access-Control-Allow-Origin: http://localhost:5174
# Access-Control-Allow-Methods: GET,POST,PUT,DELETE,OPTIONS
# Access-Control-Allow-Headers: Content-Type,Authorization,Consent-JWT
# Access-Control-Allow-Credentials: true
```

## Troubleshooting

### Problem: CORS errors in browser console
**Solution**: Add your frontend origin to `CORS_ALLOWED_ORIGINS`

### Problem: "Access-Control-Allow-Credentials" errors
**Solution**: Already configured automatically (set to `true`)

### Problem: Custom headers being blocked
**Solution**: Add them to `CORS_ALLOWED_HEADERS`

### Problem: Preflight requests failing
**Solution**: Ensure `OPTIONS` is in `CORS_ALLOWED_METHODS` (included by default)

## Debug Mode

Enable detailed CORS logging:
```bash
DEBUG_CORS=true
```

This will log:
- Origin of incoming requests
- CORS response headers
- Warnings for non-allowed origins

## Integration Examples

### Frontend JavaScript
```javascript
fetch('http://localhost:8000/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Consent-JWT': 'your-jwt-token'
  },
  credentials: 'include',  // Important!
  body: JSON.stringify({message: 'Hello Opey'})
});
```

### React/Axios
```javascript
const api = axios.create({
  baseURL: 'http://localhost:8000',
  withCredentials: true,  // Important!
  headers: {
    'Content-Type': 'application/json'
  }
});
```

## Changes Made

1. **Enhanced `src/service/service.py`**:
   - Split comma-separated origins properly
   - Added development fallbacks
   - Configurable methods and headers
   - Added CORS debug middleware
   - Better error messages and logging

2. **Added comprehensive documentation**:
   - `docs/CORS_CONFIGURATION.md` - Detailed guide
   - `scripts/test_cors.py` - Testing tool

3. **Maintained backward compatibility**:
   - Old single-origin configs still work
   - No breaking changes to existing setups

## Next Steps

1. **For immediate use**: No action needed for development - CORS will work out of the box
2. **For production**: Set `CORS_ALLOWED_ORIGINS` to your production domain(s)
3. **For debugging**: Enable `DEBUG_CORS=true` to see detailed logs
4. **For testing**: Run the CORS test script to verify everything works

The CORS configuration is now robust, secure, and ready for both development and production use.