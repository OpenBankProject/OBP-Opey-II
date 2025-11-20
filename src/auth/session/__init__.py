"""HTTP session management for authentication and user state."""

from .config import session_cookie, backend, session_verifier
from .models import SessionData

__all__ = [
    "session_cookie",
    "backend", 
    "session_verifier",
    "SessionData",
]
