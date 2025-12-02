import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger('opey.service.middleware')


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware to properly format error responses for Portal consumption"""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException as exc:
            # Http Exceptions should be handled by fastapi's default handler or the custom one we set up
            raise
        except Exception as exc:
            # Handle unexpected errors
            logger.error(f"Unexpected error for {request.url}: {str(exc)}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error occurred",
                    "error_code": "internal_error",
                    "message": "An unexpected error occurred. Please try again later.",
                    "action_required": "Please refresh the page and try again"
                }
            )
