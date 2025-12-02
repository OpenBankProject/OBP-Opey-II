"""
FastAPI dependencies for the Opey service.

This module provides reusable dependency functions that can be injected
into route handlers throughout the application.
"""
from functools import lru_cache
from auth.auth import AuthConfig, OBPConsentAuth
from .opey_session import OpeySession
from fastapi import Depends
from .streaming.stream_manager import StreamManager


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

def get_stream_manager(opey_session: OpeySession = Depends()) -> StreamManager:
    """Returns a configured StreamManager instance as a FastAPI dependency."""
    return StreamManager(opey_session)