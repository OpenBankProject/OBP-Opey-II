import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException

logger = logging.getLogger('opey.service.middleware')


class RateLimitKeyMiddleware(BaseHTTPMiddleware):
    """Pre-load session data for rate limiting key generation"""
    
    async def dispatch(self, request: Request, call_next):
        try:
            from auth.session import backend, session_cookie
            
            # Use session_cookie to extract and verify the session ID
            # This handles the signed cookie properly (session_cookie is a dependency, not async)
            try:
                session_id = session_cookie(request)
                session_data = await backend.read(session_id)
                
                if session_data:
                    # Attach to request.state so slowapi key_func can access it
                    request.state.session_data = session_data
                    logger.debug(f"Rate limit session loaded for user_id={session_data.user_id}")
            except HTTPException:
                # session_cookie raises HTTPException when cookie is missing or invalid
                # This is expected for exempt endpoints like /create-session
                pass
            except Exception as e:
                logger.warning(f"Error loading session for rate limiting: {e}")
                
        except Exception as e:
            logger.error(f"Unexpected error in rate limit middleware: {e}", exc_info=True)
            
        return await call_next(request)