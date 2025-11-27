import logging
import os
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

logger = logging.getLogger('opey.service.middleware')


class CORSDebugMiddleware(BaseHTTPMiddleware):
    """Middleware to log CORS-related information for debugging"""
    
    def __init__(self, app, cors_allowed_origins: list[str]):
        super().__init__(app)
        self.cors_allowed_origins = cors_allowed_origins
    
    async def dispatch(self, request: Request, call_next):
        # Log CORS-related headers for debugging
        origin = request.headers.get("origin")
        if origin:
            logger.debug(f"CORS request from origin: {origin}")
            if origin not in self.cors_allowed_origins:
                logger.warning(f"Request from non-allowed origin: {origin}")

        response = await call_next(request)

        # Log response CORS headers
        if origin:
            cors_headers = {
                k: v for k, v in response.headers.items()
                if k.lower().startswith('access-control-')
            }
            if cors_headers:
                logger.debug(f"CORS response headers: {cors_headers}")

        return response
