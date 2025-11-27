import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

logger = logging.getLogger('opey.service.middleware')


class SessionUpdateMiddleware(BaseHTTPMiddleware):
    """Middleware to update session data in backend after request processing"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Update session data if it exists in the request state
        if hasattr(request.state, 'session_data') and hasattr(request.state, 'session_id'):
            try:
                from auth.session import backend
                await backend.update(request.state.session_id, request.state.session_data)
            except Exception as e:
                logger.error(f"Failed to update session data: {e}")

        return response
