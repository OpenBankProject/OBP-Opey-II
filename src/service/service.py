import json
import os
from contextlib import asynccontextmanager
from typing import Any, Annotated, AsyncGenerator
import uuid
import logging

from fastapi import FastAPI, HTTPException, Request, Response, status, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langsmith import Client as LangsmithClient

from auth.auth import OBPConsentAuth, AuthConfig
from auth.session import session_cookie, backend, SessionData

from service.opey_session import OpeySession
from service.checkpointer import checkpointers

from .streaming import StreamManager

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
    # Ensures that the checkpointer is created and closed properly, and that only this one is used
    # for the whole app
    async with AsyncSqliteSaver.from_conn_string('checkpoints.db') as sql_checkpointer:
        checkpointers['aiosql'] = sql_checkpointer
        yield


app = FastAPI(lifespan=lifespan)

# Add session update middleware
app.add_middleware(SessionUpdateMiddleware)


# Setup CORS policy
if cors_allowed_origins := os.getenv("CORS_ALLOWED_ORIGINS"):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    raise ValueError("CORS_ALLOWED_ORIGINS environment variable must be set")

# Define Allowed Authentication methods,
# Currently only OBP consent is allowed
auth_config = AuthConfig({
    "obp_consent": OBPConsentAuth(),
})

obp_base_url = os.getenv('OBP_BASE_URL')

@app.post("/create-session")
async def create_session(request: Request, response: Response):
    """
    Create a session for the user using the OBP consent JWT or create an anonymous session.
    """
    # Get the consent JWT from the request
    consent_jwt = request.headers.get("Consent-JWT")
    allow_anonymous = os.getenv("ALLOW_ANONYMOUS_SESSIONS", "false").lower() == "true"

    logger.info(f"CREATE SESSION REQUEST - JWT present: {bool(consent_jwt)}, Anonymous allowed: {allow_anonymous}")

    if not consent_jwt:
        if not allow_anonymous:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization headers, Must be one of ['Consent-JWT']"
            )

        # Create anonymous session
        logger.info("Creating anonymous session")
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

    # Check if the consent JWT is valid
    if not await auth_config.obp_consent.acheck_auth(consent_jwt):
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

    return SessionCreateResponse(
        message="Authenticated session created",
        session_type="authenticated"
    )


@app.post("/delete-session")
async def delete_session(response: Response, session_id: uuid.UUID = Depends(session_cookie)):
    await backend.delete(session_id)
    session_cookie.delete_from_response(response)
    response.status_code = 200
    response.body = b"session deleted"
    return response


@app.get("/status", dependencies=[Depends(session_cookie)])
async def get_status(opey_session: Annotated[OpeySession, Depends()]) -> dict[str, Any]:
    """Health check endpoint with usage information."""
    if not opey_session.graph:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    status_info = {
        "status": "ok",
        "usage": opey_session.get_usage_info()
    }

    return status_info

@app.post("/invoke", dependencies=[Depends(session_cookie)])
async def invoke(user_input: UserInput, request: Request, opey_session: Annotated[OpeySession, Depends()]) -> ChatMessage:
    """
    Invoke the agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    """
    # Update request count for usage tracking
    opey_session.update_request_count()

    agent: CompiledStateGraph = opey_session.graph
    kwargs, run_id = _parse_input(user_input)
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


async def opey_message_generator(user_input: StreamInput, opey_session: OpeySession) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent using the new streaming system.

    This is the workhorse method for the /stream endpoint.
    """

    logger.debug(f"Received stream request: {user_input}")

    # Parse input to get config
    thread_id = user_input.thread_id or str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id}
    }

    print(f"------------START STREAM-----------\n\n")

    # Use the new stream manager
    stream_manager = StreamManager(opey_session)

    async for stream_event in stream_manager.stream_response(user_input, config):
        yield stream_manager.to_sse_format(stream_event)


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


@app.post("/stream", response_class=StreamingResponse, responses=_sse_response_example(), dependencies=[Depends(session_cookie)])
async def stream_agent(user_input: StreamInput, request: Request, opey_session: Annotated[OpeySession, Depends()]) -> StreamingResponse:
    """
    Stream the agent's response to a user input, including intermediate messages and tokens.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    """
    # Update request count for usage tracking
    opey_session.update_request_count()

    async def stream_generator():
        async for msg in opey_message_generator(user_input, opey_session):
            yield msg

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/approval/{thread_id}", response_class=StreamingResponse, responses=_sse_response_example(), dependencies=[Depends(session_cookie)])
async def user_approval(user_approval_response: ToolCallApproval, thread_id: str, opey_session: Annotated[OpeySession, Depends()]) -> StreamingResponse:
    print(f"[DEBUG] Approval endpoint user_response: {user_approval_response}\n")

    # Create stream input for approval continuation
    user_input = StreamInput(
        message="",
        thread_id=thread_id,
        is_tool_call_approval=True,
    )

    # Use the new stream manager for approval handling
    stream_manager = StreamManager(opey_session)

    approved = user_approval_response.approval == "approve"

    async def stream_generator():
        async for stream_event in stream_manager.continue_after_approval(
            thread_id=thread_id,
            tool_call_id=user_approval_response.tool_call_id,
            approved=approved,
            stream_input=user_input
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
    if not await auth_config.obp_consent.acheck_auth(consent_jwt):
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
