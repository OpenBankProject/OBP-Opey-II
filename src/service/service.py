import json
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Annotated, AsyncGenerator
import uuid
import logging

from fastapi import FastAPI, HTTPException, Request, Response, status, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.exception_handlers import http_exception_handler

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langsmith import Client as LangsmithClient

from auth.auth import OBPConsentAuth, AuthConfig
from auth.session import session_cookie, backend, SessionData

from service.opey_session import OpeySession
from service.checkpointer import checkpointers
from service.redis_client import get_redis_client, redis_clients

from .streaming import StreamManager
from .streaming_legacy import _parse_input
from .streaming.orchestrator_repository import orchestrator_repository

from schema import (
    ChatMessage,
    Feedback,
    FeedbackResponse,
    StreamInput,
    UserInput,
    convert_message_content_to_string,
    ToolCallApproval,
    SessionCreateResponse,
    UsageInfoResponse,
    SessionUpgradeResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('opey.service')


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all requests and responses for debugging authentication issues"""

    async def dispatch(self, request: Request, call_next):
        # Log incoming request details
        logger.debug(f"REQUEST_DEBUG: {request.method} {request.url}")
        logger.debug(f"REQUEST_DEBUG: Headers: {dict(request.headers)}")

        # Check for session cookie specifically
        session_cookie_value = request.cookies.get("session")
        logger.debug(f"REQUEST_DEBUG: Session cookie present: {bool(session_cookie_value)}")
        if session_cookie_value:
            logger.debug(f"REQUEST_DEBUG: Session cookie length: {len(session_cookie_value)}")

        try:
            response = await call_next(request)

            # Log response details
            logger.debug(f"RESPONSE_DEBUG: Status {response.status_code}")
            logger.debug(f"RESPONSE_DEBUG: Headers: {dict(response.headers)}")

            # For error responses, try to log the body
            if response.status_code >= 400:
                logger.error(f"ERROR_RESPONSE_DEBUG: Status {response.status_code} for {request.url}")

            return response

        except HTTPException as exc:
            logger.error(f"HTTP_EXCEPTION_DEBUG: Status {exc.status_code}, Detail: {exc.detail}")
            logger.error(f"HTTP_EXCEPTION_DEBUG: Exception type: {type(exc)}")
            raise
        except Exception as exc:
            logger.error(f"UNEXPECTED_EXCEPTION_DEBUG: {type(exc)}: {str(exc)}")
            raise


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


class SessionUpdateMiddleware(BaseHTTPMiddleware):
    """Middleware to update session data in backend after request processing"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Update session data if it exists in the request state
        if hasattr(request.state, 'session_data') and hasattr(request.state, 'session_id'):
            try:
                await backend.update(request.state.session_id, request.state.session_data)
            except Exception as e:
                logger.error(f"Failed to update session data: {e}")

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Initialize redis client
    redis_client = await get_redis_client()

    cleanup_task = asyncio.create_task(periodic_orchestrator_cleanup())
    
    # Ensures that the checkpointer is created and closed properly, and that only this one is used
    # for the whole app
    async with AsyncSqliteSaver.from_conn_string('checkpoints.db') as sql_checkpointer:
        checkpointers['aiosql'] = sql_checkpointer
        yield

    # Cancel cleanup task during shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("Orchestrator cleanup task cancelled during shutdown")


async def periodic_orchestrator_cleanup(interval_seconds: int = 600):
    """Periodically clean up inactive orchestrators"""
    while True:
        try:
            logger.info("Running scheduled cleanup of orchestrators")
            removed = orchestrator_repository.cleanup_inactive(max_age_seconds=3600)  # 1 hour timeout
            logger.info(f"Orchestrator cleanup completed: removed {removed} inactive orchestrators")
        except Exception as e:
            logger.error(f"Error during orchestrator cleanup: {e}", exc_info=True)
        
        await asyncio.sleep(interval_seconds)

app = FastAPI(lifespan=lifespan)

# Add custom exception handler for HTTPExceptions
@app.exception_handler(HTTPException)
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

# Add session update middleware
app.add_middleware(SessionUpdateMiddleware)

# Add comprehensive request/response logging for debugging
app.add_middleware(RequestResponseLoggingMiddleware)

# Add error handling middleware to format authentication errors for Portal
app.add_middleware(ErrorHandlingMiddleware)


# Setup CORS policy
cors_allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
cors_allowed_origins = [origin.strip() for origin in cors_allowed_origins if origin.strip()]

# Development fallback
if not cors_allowed_origins:
    logger.warning("CORS_ALLOWED_ORIGINS not set, using development defaults")
    cors_allowed_origins = ["http://localhost:5174", "http://localhost:3000", "http://127.0.0.1:5174", "http://127.0.0.1:3000"]

# Configure specific headers and methods for security
cors_allowed_methods = os.getenv("CORS_ALLOWED_METHODS", "GET,POST,PUT,DELETE,OPTIONS").split(",")
cors_allowed_methods = [method.strip() for method in cors_allowed_methods if method.strip()]

cors_allowed_headers = os.getenv("CORS_ALLOWED_HEADERS", "Content-Type,Authorization,Consent-JWT").split(",")
cors_allowed_headers = [header.strip() for header in cors_allowed_headers if header.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_credentials=True,
    allow_methods=cors_allowed_methods,
    allow_headers=cors_allowed_headers,
)

logger.info(f"CORS configured with origins: {cors_allowed_origins}")

# Add CORS debugging middleware for development
class CORSDebugMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Log CORS-related headers for debugging
        origin = request.headers.get("origin")
        if origin:
            logger.debug(f"CORS request from origin: {origin}")
            if origin not in cors_allowed_origins:
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

# Add debug middleware in development
if os.getenv("DEBUG_CORS", "false").lower() == "true":
    app.add_middleware(CORSDebugMiddleware)
    logger.info("CORS debug middleware enabled")

# Define Allowed Authentication methods,
# Currently only OBP consent is allowed
auth_config = AuthConfig()
auth_config.register_auth_strategy("obp_consent", OBPConsentAuth())

obp_base_url = os.getenv('OBP_BASE_URL')

@app.post("/create-session")
async def create_session(request: Request, response: Response):
    """
    Create a session for the user using the OBP consent JWT or create an anonymous session.
    """
    # Get the consent JWT from the request
    logger.info("Hello from create_session")
    consent_jwt = request.headers.get("Consent-JWT")
    logger.info(f"Consent JWT: {consent_jwt}")
    allow_anonymous = os.getenv("ALLOW_ANONYMOUS_SESSIONS", "false").lower() == "true"

    logger.info(f"CREATE SESSION REQUEST - JWT present: {bool(consent_jwt)}, Anonymous allowed: {allow_anonymous}")

    # DEBUG: Log detailed request information
    logger.debug(f"create_session - Request headers: {dict(request.headers)}")
    if consent_jwt:
        masked_jwt = f"{consent_jwt[:20]}...{consent_jwt[-10:]}" if len(consent_jwt) > 30 else consent_jwt[:10] + "..." if len(consent_jwt) > 10 else consent_jwt
        logger.debug(f"create_session - Consent JWT length: {len(consent_jwt)} chars, masked: {masked_jwt}")
    logger.debug(f"create_session - Environment ALLOW_ANONYMOUS_SESSIONS: {os.getenv('ALLOW_ANONYMOUS_SESSIONS', 'not set')}")

    if not consent_jwt:
        logger.info("create_session sayz: No Consent-JWT provided")
        logger.debug("create_session - No Consent-JWT header found in request")
        if not allow_anonymous:
            logger.debug("create_session - Anonymous sessions not allowed, returning 401")
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization headers, Must be one of ['Consent-JWT']"
            )

        # Create anonymous session
        logger.info("Creating anonymous session")
        logger.debug("create_session - Proceeding to create anonymous session")
        session_id = uuid.uuid4()
        session_data = SessionData(
            consent_jwt=None,
            is_anonymous=True,
            token_usage=0,
            request_count=0
        )

        await backend.create(session_id, session_data)
        session_cookie.attach_to_response(response, session_id)

        return SessionCreateResponse(
            message="Anonymous session created",
            session_type="anonymous",
            usage_limits={
                "token_limit": int(os.getenv("ANONYMOUS_SESSION_TOKEN_LIMIT", 10000)),
                "request_limit": int(os.getenv("ANONYMOUS_SESSION_REQUEST_LIMIT", 20))
            }
        )
    else:
        logger.info("create_session sayz: Consent-JWT provided")
        logger.debug("create_session - Processing authenticated session with Consent-JWT")
    # Check if the consent JWT is valid
    # if not await auth_config.obp_consent.acheck_auth(consent_jwt):
    #     raise HTTPException(status_code=401, detail="Invalid Consent-JWT")
    logger.info("Create session sayz: creating session_id")
    if not await auth_config.auth_strategies["obp_consent"].acheck_auth(consent_jwt):
        raise HTTPException(status_code=401, detail="Invalid Consent-JWT")

    session_id = uuid.uuid4()

    # Create a session using the OBP consent JWT
    session_data = SessionData(
        consent_jwt=consent_jwt,
        is_anonymous=False,
        token_usage=0,
        request_count=0
    )

    await backend.create(session_id, session_data)
    session_cookie.attach_to_response(response, session_id)

    logger.info("Creating authenticated session")

    session_create_response = SessionCreateResponse(
        message="Authenticated session created",
        session_type="authenticated"
    )
    # print(SessionCreateResponse.message())
    return session_create_response


@app.post("/delete-session")
async def delete_session(response: Response, session_id: uuid.UUID = Depends(session_cookie)):
    await backend.delete(session_id)
    session_cookie.delete_from_response(response)
    response.status_code = 200
    response.body = b"session deleted"
    return response


@app.get("/status")
async def get_status() -> dict[str, Any]:
    """Health check endpoint with usage information."""

    status_info = {
        "status": "ok",
    }

    return status_info

@app.post("/invoke", dependencies=[Depends(session_cookie)])
async def invoke(user_input: UserInput, request: Request, opey_session: Annotated[OpeySession, Depends()]) -> ChatMessage:
    """
    Invoke the agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    """


    logger.info(f"Hello from invoke\n")


    # Update request count for usage tracking
    opey_session.update_request_count()

    agent: CompiledStateGraph = opey_session.graph
    kwargs, run_id = _parse_input(user_input, str(opey_session.session_id))
    try:
        response = await agent.ainvoke(**kwargs)
        output = ChatMessage.from_langchain(response["messages"][-1])
        logger.info(f"Replied to thread_id {kwargs['config']['configurable']['thread_id']} with message:\n\n {output.content}\n")

        # Update token usage if available
        if hasattr(response, 'total_tokens') and response.get('total_tokens'):
            opey_session.update_token_usage(response['total_tokens'])

        output.run_id = str(run_id)
        return output
    except Exception as e:
        logging.error(f"Error invoking agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _sse_response_example() -> dict[int, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }

def get_stream_manager(opey_session: OpeySession = Depends()) -> StreamManager:
    """Returns a configured StreamManager instance as a FastAPI dependency."""
    return StreamManager(opey_session)

@app.post("/stream", response_class=StreamingResponse, responses=_sse_response_example(), dependencies=[Depends(session_cookie)])
async def stream_agent(
    user_input: StreamInput, 
    request: Request, 
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> StreamingResponse:
    """Stream the agent's response to a user input"""
    # Log successful authentication
    logger.error(f"STREAM_ENDPOINT_DEBUG: Successfully authenticated, session_id: {stream_manager.opey_session.session_id}")
    logger.error(f"STREAM_ENDPOINT_DEBUG: User input: {user_input}")

    # Update request count for usage tracking
    stream_manager.opey_session.update_request_count()

    # Get the actual thread_id that will be used
    thread_id = user_input.thread_id or str(stream_manager.opey_session.session_id)
    config = {'configurable': {'thread_id': thread_id}}

    async def stream_generator():
        async for stream_event in stream_manager.stream_response(user_input, config):
            yield stream_manager.to_sse_format(stream_event)

    # Add thread_id to response headers for frontend synchronization
    headers = {"X-Thread-ID": thread_id}

    return StreamingResponse(stream_generator(), media_type="text/event-stream", headers=headers)

@app.post("/approval/{thread_id}", response_class=StreamingResponse, responses=_sse_response_example(), dependencies=[Depends(session_cookie)])
async def user_approval(
    user_approval_response: ToolCallApproval,
    thread_id: str,
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> StreamingResponse:
    print(f"[DEBUG] Approval endpoint user_response: {user_approval_response}\n")

    # Create stream input for approval continuation
    approval_user_input = StreamInput(
        message="",
        thread_id=thread_id,
        tool_call_approval=user_approval_response,
    )

    config = {'configurable': {'thread_id': thread_id}}

    async def stream_generator():
        async for stream_event in stream_manager.stream_response(
            stream_input=approval_user_input,
            config=config,
        ):
            yield stream_manager.to_sse_format(stream_event)

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/feedback", dependencies=[Depends(session_cookie)])
async def feedback(feedback: Feedback) -> FeedbackResponse:
    """
    Record feedback for a run to LangSmith.

    This is a simple wrapper for the LangSmith create_feedback API, so the
    credentials can be stored and managed in the service rather than the client.
    See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
    """
    client = LangsmithClient()
    kwargs = feedback.kwargs or {}
    client.create_feedback(
        run_id=feedback.run_id,
        key=feedback.key,
        score=feedback.score,
        **kwargs,
    )
    return FeedbackResponse()


@app.get("/usage", dependencies=[Depends(session_cookie)])
async def get_usage(opey_session: Annotated[OpeySession, Depends()]) -> UsageInfoResponse:
    """
    Get detailed usage information for the current session.
    """
    usage_info = opey_session.get_usage_info()
    return UsageInfoResponse(**usage_info)


@app.post("/upgrade-session", dependencies=[Depends(session_cookie)])
async def upgrade_session(request: Request, response: Response, session_id: uuid.UUID = Depends(session_cookie)) -> SessionUpgradeResponse:
    """
    Upgrade an anonymous session to an authenticated session using OBP consent JWT.
    """
    # Get the consent JWT from the request
    consent_jwt = request.headers.get("Consent-JWT")
    if not consent_jwt:
        raise HTTPException(status_code=400, detail="Missing Consent-JWT header")

    # Check if the consent JWT is valid
    # if not await auth_config.obp_consent.acheck_auth(consent_jwt):
    #     raise HTTPException(status_code=401, detail="Invalid Consent-JWT")
    if not await auth_config.auth_strategies["obp_consent"].acheck_auth(consent_jwt):
        raise HTTPException(status_code=401, detail="Invalid Consent-JWT")

    # Get current session data
    session_data = await backend.read(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    # Only allow upgrading anonymous sessions
    if not session_data.is_anonymous:
        raise HTTPException(status_code=400, detail="Session is already authenticated")

    # Update session data to authenticated
    updated_session_data = SessionData(
        consent_jwt=consent_jwt,
        is_anonymous=False,
        token_usage=session_data.token_usage,  # Preserve usage stats
        request_count=session_data.request_count
    )

    await backend.update(session_id, updated_session_data)

    logger.info(f"Upgraded anonymous session {session_id} to authenticated session")

    return SessionUpgradeResponse(
        message="Session successfully upgraded to authenticated",
        session_type="authenticated",
        previous_usage={
            "tokens_used": session_data.token_usage,
            "requests_made": session_data.request_count
        }
    )

# @app.post("/auth")
# async def auth(consent_auth_body: ConsentAuthBody, response: Response):
#     """
#     Authorize Opey using an OBP consent
#     """
#     logger.debug("Authorizing Opey using an OBP consent")
#     version = os.getenv("OBP_API_VERSION")
#     consent_challenge_answer_path = f"/obp/{version}/banks/gh.29.uk/consents/{consent_auth_body.consent_id}/challenge"

#     # Check consent challenge answer
#     try:
#         obp_response = await obp_requests("POST", consent_challenge_answer_path, json.dumps({"answer": consent_auth_body.consent_challenge_answer}))
#     except Exception as e:
#         logger.error(f"Error in /auth endpoint: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

#     if obp_response and not (200 <= obp_response.status < 300):
#         logger.debug("Welp, we got an error from OBP")
#         message = await obp_response.text()
#         raise HTTPException(status_code=obp_response.status, detail=message)

#     try:
#         payload = {
#             "consent_id": consent_auth_body.consent_id,
#         }
#         opey_jwt = sign_jwt(payload)
#     except Exception as e:
#         logger.debug("Looks like signing the JWT failed OMG")
#         logger.error(f"Error in /auth endpoint: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

#     print("got consent jwt")
#     # Set the JWT cookie
#     response.set_cookie(key="jwt", value=opey_jwt, httponly=False, samesite='lax', secure=False)
#     return AuthResponse(success=True)
