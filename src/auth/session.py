import os

from fastapi_sessions.frontends.implementations import SessionCookie, CookieParameters
from uuid import UUID
from fastapi_sessions.backends.implementations import InMemoryBackend
from fastapi_sessions.session_verifier import SessionVerifier
from fastapi import HTTPException
from pydantic import BaseModel

# Set up sessions to use consents
class SessionData(BaseModel):
    consent_jwt: str

cookie_params = CookieParameters(
    secure=True,
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
    auth_http_exception=HTTPException(status_code=403, detail="invalid session"),
)