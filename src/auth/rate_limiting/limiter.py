import logging
import os

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


# Get Redis URL from environment, with fallback to memory storage
redis_url = os.getenv("REDIS_URL")

try:
    if redis_url:
        logger.info(f"Rate limiter using Redis storage: {redis_url}")
        limiter = Limiter(
            key_func=get_remote_address,
            storage_uri=redis_url,
            default_limits=[os.getenv("GLOBAL_RATE_LIMIT", "10/minute")],
        )
    else:
        logger.warning(
            "REDIS_URL not set - rate limiter using in-memory storage (not suitable for production)"
        )
        # Use memory storage when Redis is not available
        limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[os.getenv("GLOBAL_RATE_LIMIT", "10/minute")],
        )
except (ValueError, Exception) as e:
    logger.error(
        f"Error initializing rate limiter with Redis: {type(e).__name__}: {str(e)}"
    )
    logger.warning("Falling back to in-memory rate limiting")
    # Fallback to memory storage if Redis initialization fails
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[os.getenv("GLOBAL_RATE_LIMIT", "10/minute")],
    )
