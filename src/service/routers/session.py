from fastapi import APIRouter, Request, Response, HTTPException, Depends
import logging
import uuid
import os

from auth.session import backend, SessionData, session_cookie
from auth.auth import AuthConfig
from schema import SessionCreateResponse, SessionUpgradeResponse
from service.dependencies import get_auth_config

logger = logging.getLogger('opey.service.routers.session')

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
    Create a session for the user using the OBP consent JWT or create an anonymous session.
    """
    # Get the consent JWT from the request
    consent_id = request.headers.get("Consent-Id")
    
    # Create masked versions for logging
    masked_consent_id = f"{consent_id[:20]}...{consent_id[-10:]}" if consent_id and len(consent_id) > 30 else consent_id[:10] + "..." if consent_id and len(consent_id) > 10 else consent_id    
    logger.info(f"Consent ID: {consent_id}\n")
    
    allow_anonymous = os.getenv("ALLOW_ANONYMOUS_SESSIONS", "false").lower() == "true"

    logger.info(f"CREATE SESSION REQUEST - Consent ID present: {bool(masked_consent_id)}, Anonymous allowed: {allow_anonymous}")

    # DEBUG: Log detailed request information
    logger.debug(f"create_session - Request headers: {dict(request.headers)}")
    if consent_id:
        logger.debug(f"create_session - Consent ID length: {len(consent_id)} chars, masked: {masked_consent_id}")
    logger.debug(f"create_session - Environment ALLOW_ANONYMOUS_SESSIONS: {os.getenv('ALLOW_ANONYMOUS_SESSIONS', 'not set')}")

    if not consent_id:
        logger.info("create_session says: No Consent-Id provided")
        logger.debug("create_session - No Consent-Id header found in request")
        if not allow_anonymous:
            logger.debug("create_session - Anonymous sessions not allowed, returning 401")
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization headers, Must be one of ['Consent-Id']"
            )

        # Create anonymous session
        logger.info("Creating anonymous session")
        logger.debug("create_session - Proceeding to create anonymous session")
        session_id = uuid.uuid4()
        session_data = SessionData(
            consent_id=None,
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
        logger.info("create_session says: Consent-Id provided")
        logger.debug("create_session - Processing authenticated session with Consent-Id")
    
    logger.info("Create session says: creating session_id")
    if not await auth_config.auth_strategies["obp_consent_id"].acheck_auth(consent_id):
        raise HTTPException(status_code=401, detail="Invalid Consent-Id")

    # Fetch user_id of consenter
    auth = auth_config.auth_strategies["obp_consent_id"]
    user_data = await auth.get_current_user(consent_id)
    user_id = user_data.get("user_id") if user_data else None
    
    if not user_id:
        raise HTTPException(status_code=403, detail="Could not retrieve user information from Consent-Id")

    session_id = uuid.uuid4()

    # Create a session using the OBP consent JWT
    session_data = SessionData(
        consent_id=consent_id,
        is_anonymous=False,
        token_usage=0,
        request_count=0,
        user_id=user_id
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

    # Update session data to authenticated
    updated_session_data = SessionData(
        consent_id=consent_id,
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