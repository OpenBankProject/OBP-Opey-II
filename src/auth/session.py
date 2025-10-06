import os

from fastapi_sessions.frontends.implementations import SessionCookie, CookieParameters
from uuid import UUID
from fastapi_sessions.backends.implementations import InMemoryBackend
from fastapi_sessions.session_verifier import SessionVerifier
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional

# Set up sessions to use consents
class SessionData(BaseModel):
    consent_jwt: Optional[str] = None
    is_anonymous: bool = False
    token_usage: int = 0
    request_count: int = 0

# For development, allow insecure cookies over HTTP
secure_cookies = os.getenv("SECURE_COOKIES", "true").lower() == "true"

cookie_params = CookieParameters(
    secure=secure_cookies,
    samesite="lax",
    domain=os.getenv("COOKIE_DOMAIN"),  # Set to .example.com for subdomain sharing, None for localhost
    path="/",
)

# Get secret key from environment variable
if not (secret_key := os.getenv("SESSION_SECRET_KEY")):
    raise ValueError("SESSION_SECRET_KEY environment variable must be set")

# Uses UUID
session_cookie = SessionCookie(
    cookie_name="session",
    identifier="session_verifier",
    auto_error=True,
    secret_key=secret_key,
    cookie_params=cookie_params,
)

backend = InMemoryBackend[UUID, SessionData]()


class BasicVerifier(SessionVerifier[UUID, SessionData]):
    def __init__(
        self,
        *,
        identifier: str,
        auto_error: bool,
        backend: InMemoryBackend[UUID, SessionData],
        auth_http_exception: HTTPException,
    ):
        self._identifier = identifier
        self._auto_error = auto_error
        self._backend = backend
        self._auth_http_exception = auth_http_exception

    @property
    def identifier(self):
        return self._identifier

    @property
    def backend(self):
        return self._backend

    @property
    def auto_error(self):
        return self._auto_error

    @property
    def auth_http_exception(self):
        return self._auth_http_exception

    def verify_session(self, model: SessionData) -> bool:
        """If the session exists, it is valid"""
        return True


session_verifier = BasicVerifier(
    identifier="session_verifier",
    auto_error=True,
    backend=backend,
    auth_http_exception=HTTPException(
        status_code=403,
        detail={
            "error": "Authentication required: Please log in to use Opey",
            "error_code": "session_invalid",
            "message": "Your session has expired or is invalid. Please refresh the page and log in again.",
            "action_required": "Please authenticate with the OBP Portal to continue using Opey"
        }
    ),
)
