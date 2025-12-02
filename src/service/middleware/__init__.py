import os
import logging as log
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from .logging import RequestResponseLoggingMiddleware
from .rate_limit import RateLimitKeyMiddleware
from .error_handling import ErrorHandlingMiddleware
from .session import SessionUpdateMiddleware
from .cors_debug import CORSDebugMiddleware
from .exception_handlers import custom_http_exception_handler

logger = log.getLogger('opey.service.middleware')


def setup_middleware(
    app: FastAPI,
    cors_allowed_origins: list[str],
    cors_allowed_methods: list[str],
    cors_allowed_headers: list[str]
):
    """
    Setup all middleware for the FastAPI application.
    
    Middleware are added in reverse order (last added = first executed).
    Current order of execution:
    1. RateLimitKeyMiddleware (loads session data for rate limiting)
    2. SlowAPIMiddleware (rate limiting)
    3. CORSDebugMiddleware (optional, only in debug mode)
    4. CORSMiddleware (handles CORS)
    5. ErrorHandlingMiddleware (catches unhandled errors)
    6. RequestResponseLoggingMiddleware (logs requests/responses)
    7. SessionUpdateMiddleware (updates session data after response)
    
    Args:
        app: FastAPI application instance
        cors_allowed_origins: List of allowed CORS origins
        cors_allowed_methods: List of allowed HTTP methods
        cors_allowed_headers: List of allowed headers
    """
    # Add custom exception handler for HTTPExceptions
    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    
    # Add session update middleware (executed last, after response is ready)
    app.add_middleware(SessionUpdateMiddleware)

    # Add comprehensive request/response logging for debugging
    app.add_middleware(RequestResponseLoggingMiddleware)

    # Add error handling middleware to format authentication errors for Portal
    app.add_middleware(ErrorHandlingMiddleware)

    # Setup CORS policy
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=cors_allowed_methods,
        allow_headers=cors_allowed_headers,
    )
    
    logger.info(f"CORS configured with origins: {cors_allowed_origins}")

    # Add CORS debugging middleware for development (optional)
    if os.getenv("DEBUG_CORS", "false").lower() == "true":
        app.add_middleware(CORSDebugMiddleware, cors_allowed_origins=cors_allowed_origins)
        logger.info("CORS debug middleware enabled")
    
    # Add SlowAPI middleware for rate limiting
    app.add_middleware(SlowAPIMiddleware)
    
    # Add rate limit key middleware (executed first, loads session data)
    app.add_middleware(RateLimitKeyMiddleware)


__all__ = [
    'setup_middleware',
    'RequestResponseLoggingMiddleware',
    'RateLimitKeyMiddleware',
    'ErrorHandlingMiddleware',
    'SessionUpdateMiddleware',
    'CORSDebugMiddleware',
    'custom_http_exception_handler',
]