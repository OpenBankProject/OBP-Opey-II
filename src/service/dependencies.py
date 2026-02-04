"""
FastAPI dependencies for the Opey service.

This module provides reusable dependency functions that can be injected
into route handlers throughout the application.
"""
import logging
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from auth.auth import AuthConfig, OBPConsentAuth
from auth.session import session_verifier, SessionData, session_cookie, backend
from langgraph.checkpoint.base import BaseCheckpointSaver

from .opey_session import OpeySession
from .streaming.stream_manager import StreamManager
from .checkpointer import get_global_checkpointer

logger = logging.getLogger(__name__)


def _extract_bearer_token(request: Request) -> str | None:
    """Extract bearer token from Authorization header if present."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]  # Strip "Bearer " prefix
    return None


@lru_cache
def get_auth_config() -> AuthConfig:
    """
    Get the application's authentication configuration.
    
    This is cached as a singleton to avoid recreating the auth config
    on every request. The auth config is immutable after initialization.
    
    Returns:
        Configured AuthConfig instance with registered auth strategies
    """
    auth_config = AuthConfig()
    auth_config.register_auth_strategy("obp_consent_id", OBPConsentAuth())
    return auth_config


async def get_opey_session(
    request: Request,
    session_data: Annotated[SessionData, Depends(session_verifier)],
    session_id: Annotated[UUID, Depends(session_cookie)],
    checkpointer: Annotated[BaseCheckpointSaver, Depends(get_global_checkpointer)],
) -> OpeySession:
    """
    Async dependency for creating fully initialized OpeySession instances.
    
    Implements hybrid bearer token handling:
    - Extracts fresh token from Authorization header if present
    - Falls back to stored session token if no header
    - Updates session if header token differs from stored
    
    Args:
        request: FastAPI request
        session_data: Validated session data from cookie
        session_id: Session UUID from cookie
        checkpointer: LangGraph checkpointer for persistence
        
    Returns:
        Fully initialized OpeySession with loaded tools
    """
    # Hybrid token handling: prefer fresh header token, fallback to stored
    header_token = _extract_bearer_token(request)
    stored_token = session_data.bearer_token
    
    # Determine which token to use
    bearer_token = header_token or stored_token
    
    # Update stored token if header provides a new one
    if header_token and header_token != stored_token:
        logger.debug(f"Updating stored bearer token for session {session_id}")
        session_data.bearer_token = header_token
        await backend.update(session_id, session_data)
    
    session = OpeySession(request, session_data, session_id, checkpointer)
    await session.async_init(bearer_token=bearer_token)
    return session


def get_stream_manager(opey_session: Annotated[OpeySession, Depends(get_opey_session)]) -> StreamManager:
    """Returns a configured StreamManager instance as a FastAPI dependency."""
    return StreamManager(opey_session)