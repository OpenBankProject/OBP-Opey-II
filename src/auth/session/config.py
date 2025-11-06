import os
import logging

from fastapi_sessions.frontends.implementations import SessionCookie, CookieParameters
from fastapi_sessions.frontends.implementations.cookie import SameSiteEnum
from uuid import UUID
from fastapi_sessions.backends.implementations import InMemoryBackend
from .backends.redis_backend import RedisBackend
from fastapi_sessions.session_verifier import SessionVerifier
from fastapi import HTTPException
from service.redis_client import get_redis_client
from pydantic import BaseModel
from typing import Optional
from .models import SessionData

logger = logging.getLogger('opey.session.config')
# For development, allow insecure cookies over HTTP
secure_cookies = os.getenv("SECURE_COOKIES", "true").lower() == "true"

cookie_params = CookieParameters(
    secure=secure_cookies,
    samesite=SameSiteEnum.none,
    domain=None,  # Allow cookies on any domain including localhost
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

redis_client = get_redis_client()
if not redis_client:
    logger.warning("Could not get Redis client, falling back to InMemoryBackend for sessions")
    backend = InMemoryBackend[UUID, SessionData]()
else:
    backend = RedisBackend[UUID, SessionData](redis_client=redis_client, session_model=SessionData)


class BasicVerifier(SessionVerifier[UUID, SessionData]):
    def __init__(
        self,
        *,
        identifier: str,
        auto_error: bool,
        backend: InMemoryBackend[UUID, SessionData] | RedisBackend[UUID, SessionData],
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
