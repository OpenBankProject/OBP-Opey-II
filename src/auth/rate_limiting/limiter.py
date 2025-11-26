import logging
import os

from typing import Callable
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def _rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Custom handler for rate limit exceeded errors"""
    # Handle both RateLimitExceeded and other exceptions gracefully
    if isinstance(exc, RateLimitExceeded):
        detail = exc.detail if hasattr(exc, "detail") else str(exc)
        error_message = f"Rate limit exceeded: {detail}"
    else:
        # For other exceptions (like ValueError), provide a generic message
        error_message = "Rate limit error occurred"
        logger.error(
            f"Unexpected error in rate limiter: {type(exc).__name__}: {str(exc)}"
        )

    return JSONResponse(
        status_code=429,
        content={
            "error": error_message,
            "error_code": "rate_limit_exceeded",
            "message": "Too many requests. Please try again later.",
        },
    )



    
def create_limiter(key_func: Callable) -> Limiter:
    """
    Create and configure a rate limiter using Redis as the backend storage.
    Args:
        key_func (Callable): Function to extract the key for rate limiting (e.g., IP address or User ID).
    Returns:
    """
    # Get Redis URL from environment, with fallback to memory storage
    redis_url = os.getenv("REDIS_URL")

    try:
        if redis_url:
            logger.info(f"Rate limiter using Redis storage: {redis_url}")
            return Limiter(
                key_func=key_func,
                storage_uri=redis_url,
                default_limits=[os.getenv("GLOBAL_RATE_LIMIT", "10/minute")],
            )
        else:
            logger.warning(
                "REDIS_URL not set - rate limiter using in-memory storage (not suitable for production)"
            )
            # Use memory storage when Redis is not available
            return Limiter(
                key_func=key_func,
                default_limits=[os.getenv("GLOBAL_RATE_LIMIT", "10/minute")],
            )
    except (ValueError, Exception) as e:
        logger.error(
            f"Error initializing rate limiter with Redis: {type(e).__name__}: {str(e)}"
        )
        logger.warning("Falling back to in-memory rate limiting")
        # Fallback to memory storage if Redis initialization fails
        return Limiter(
            key_func=key_func,
            default_limits=[os.getenv("GLOBAL_RATE_LIMIT", "10/minute")],
        )
        
        
def get_user_id_from_request(request: Request) -> str:
    """
    Extract user ID from request for rate limiting.
    Returns user:{user_id} for authenticated users.
    Returns anonymous for anonymous sessions.
    Returns unauthenticated for requests without any session.
    
    Note: Endpoints that don't require authentication should use @limiter.exempt
    """
    if hasattr(request.state, "session_data"):
        session_data = request.state.session_data
        
        if session_data and hasattr(session_data, 'user_id') and session_data.user_id:
            logger.debug(f"Rate limiting by user_id: {session_data.user_id}")
            return f"user:{session_data.user_id}"
        else:
            # Has session but no user_id - anonymous session
            logger.debug("Rate limiting anonymous session")
            return "anonymous"
    else:
        # No session at all - likely hitting an exempt endpoint or initial request
        logger.debug("No session data for rate limiting - using default key")
        return "unauthenticated"
        