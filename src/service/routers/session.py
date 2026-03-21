from fastapi import APIRouter, Request, Response, HTTPException, Depends
import logging
import uuid
import os

from auth.session import backend, SessionData, session_cookie
from auth.auth import AuthConfig
from schema import SessionCreateResponse, SessionUpgradeResponse
from service.dependencies import get_auth_config

logger = logging.getLogger('opey.service.routers.session')


def _extract_bearer_token(request: Request) -> str | None:
    """Extract bearer token from Authorization header if present."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]  # Strip "Bearer " prefix
    return None


router = APIRouter(
    tags=["session"], 
)


@router.post("/create-session")
async def create_session(
    request: Request, 
    response: Response,
    auth_config: AuthConfig = Depends(get_auth_config)
):
    """
    Create a session for the user.

    Auth priority:
    1. Bearer token (validated against OBP /users/current)
    2. Consent-Id header (backward compatibility)
    3. Anonymous session (if allowed)
    """
    bearer_token = _extract_bearer_token(request)
    consent_id = request.headers.get("Consent-Id")
    allow_anonymous = os.getenv("ALLOW_ANONYMOUS_SESSIONS", "false").lower() == "true"

    logger.info(f"CREATE SESSION REQUEST - Bearer present: {bool(bearer_token)}, Consent-Id present: {bool(consent_id)}, Anonymous allowed: {allow_anonymous}")
    logger.debug(f"create_session - Request headers: {dict(request.headers)}")

    if bearer_token:
        # PRIMARY: Validate bearer token against OBP
        logger.info("create_session: Authenticating via Bearer token")
        bearer_auth = auth_config.auth_strategies["obp_bearer"]

        if not await bearer_auth.acheck_auth(bearer_token):
            raise HTTPException(status_code=401, detail="Invalid Bearer token")

        user_data = await bearer_auth.get_current_user(bearer_token)
        user_id = user_data.get("user_id") if user_data else None

        if not user_id:
            raise HTTPException(status_code=403, detail="Could not retrieve user information from Bearer token")

        session_id = uuid.uuid4()
        session_data = SessionData(
            consent_id=consent_id,  # Store consent_id too if provided
            is_anonymous=False,
            token_usage=0,
            request_count=0,
            user_id=user_id,
            bearer_token=bearer_token,
        )

        await backend.create(session_id, session_data)
        session_cookie.attach_to_response(response, session_id)

        logger.info("Creating authenticated session via Bearer token")
        return SessionCreateResponse(
            message="Authenticated session created",
            session_type="authenticated"
        )

    elif consent_id:
        # BACKWARD COMPAT: Consent-Id flow
        logger.info("create_session: Authenticating via Consent-Id")

        if not await auth_config.auth_strategies["obp_consent_id"].acheck_auth(consent_id):
            raise HTTPException(status_code=401, detail="Invalid Consent-Id")

        auth = auth_config.auth_strategies["obp_consent_id"]
        user_data = await auth.get_current_user(consent_id)
        user_id = user_data.get("user_id") if user_data else None

        if not user_id:
            raise HTTPException(status_code=403, detail="Could not retrieve user information from Consent-Id")

        session_id = uuid.uuid4()
        session_data = SessionData(
            consent_id=consent_id,
            is_anonymous=False,
            token_usage=0,
            request_count=0,
            user_id=user_id,
            bearer_token=None,
        )

        await backend.create(session_id, session_data)
        session_cookie.attach_to_response(response, session_id)

        logger.info("Creating authenticated session via Consent-Id")
        return SessionCreateResponse(
            message="Authenticated session created",
            session_type="authenticated"
        )

    else:
        # ANONYMOUS: No auth headers provided
        logger.info("create_session: No auth headers provided")
        if not allow_anonymous:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization headers. Must provide one of: 'Authorization: Bearer <token>' or 'Consent-Id'"
            )

        logger.info("Creating anonymous session")
        session_id = uuid.uuid4()
        session_data = SessionData(
            consent_id=None,
            is_anonymous=True,
            token_usage=0,
            request_count=0,
            bearer_token=None,
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

@router.post("/delete-session")
async def delete_session(response: Response, session_id: uuid.UUID = Depends(session_cookie)):
    await backend.delete(session_id)
    session_cookie.delete_from_response(response)
    response.status_code = 200
    response.body = b"session deleted"
    return response

@router.post("/upgrade-session", dependencies=[Depends(session_cookie)])
async def upgrade_session(
    request: Request, 
    response: Response, 
    session_id: uuid.UUID = Depends(session_cookie),
    auth_config: AuthConfig = Depends(get_auth_config)
) -> SessionUpgradeResponse:
    """
    Upgrade an anonymous session to an authenticated session using OBP consent JWT.
    """
    # Get the consent JWT from the request
    consent_id = request.headers.get("Consent-Id")
    if not consent_id:
        raise HTTPException(status_code=400, detail="Missing Consent-Id header")

   
    if not await auth_config.auth_strategies["obp_consent_id"].acheck_auth(consent_id):
        raise HTTPException(status_code=401, detail="Invalid Consent-Id")

    # Get current session data
    session_data = await backend.read(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    # Only allow upgrading anonymous sessions
    if not session_data.is_anonymous:
        raise HTTPException(status_code=400, detail="Session is already authenticated")

    # Extract bearer token (new or preserve existing)
    bearer_token = _extract_bearer_token(request) or session_data.bearer_token

    # Update session data to authenticated
    updated_session_data = SessionData(
        consent_id=consent_id,
        is_anonymous=False,
        token_usage=session_data.token_usage,  # Preserve usage stats
        request_count=session_data.request_count,
        bearer_token=bearer_token,
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