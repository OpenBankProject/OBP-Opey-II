import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler

logger = logging.getLogger('opey.service.middleware')


async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """Custom handler for HTTPExceptions to ensure proper error formatting for Portal"""
    logger.error(f"CUSTOM_EXCEPTION_HANDLER: {exc.status_code} - {exc.detail}")

    if exc.status_code == 403:
        # Format authentication errors specifically for Portal
        if isinstance(exc.detail, dict):
            error_response = exc.detail
        else:
            error_response = {
                "error": "Authentication required: Please log in to use Opey",
                "error_code": "authentication_failed",
                "message": str(exc.detail) if exc.detail else "Session invalid or expired",
                "action_required": "Please authenticate with the OBP Portal to continue using Opey"
            }

        logger.error(f"AUTH_ERROR_RESPONSE: {error_response}")
        return JSONResponse(
            status_code=403,
            content=error_response,
            headers={"Content-Type": "application/json"}
        )

    # For other HTTP exceptions, use default handler but log the details
    logger.error(f"OTHER_HTTP_EXCEPTION: {exc.status_code} - {exc.detail}")
    return await http_exception_handler(request, exc)
