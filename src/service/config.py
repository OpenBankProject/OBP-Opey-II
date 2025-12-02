"""
Configuration setup for the Opey service.

This module handles all configuration initialization including:
- CORS settings
- Authentication configuration
- Rate limiting setup
- Environment variables parsing
"""
import os
import logging
from typing import Tuple
from fastapi import FastAPI

from auth.auth import AuthConfig, OBPConsentAuth
from auth.rate_limiting import create_limiter, _rate_limit_exceeded_handler, get_user_id_from_request
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger('opey.service.config')


def get_cors_config() -> Tuple[list[str], list[str], list[str]]:
    """
    Parse and return CORS configuration from environment variables.
    
    Returns:
        Tuple containing (origins, methods, headers) lists
    """
    # Parse allowed origins
    cors_allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    cors_allowed_origins = [origin.strip() for origin in cors_allowed_origins if origin.strip()]

    # Development fallback
    if not cors_allowed_origins:
        logger.warning("CORS_ALLOWED_ORIGINS not set, using development defaults")
        cors_allowed_origins = [
            "http://localhost:5174",
            "http://localhost:3000",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:3000"
        ]

    # Parse allowed methods
    cors_allowed_methods = os.getenv("CORS_ALLOWED_METHODS", "GET,POST,PUT,DELETE,OPTIONS").split(",")
    cors_allowed_methods = [method.strip() for method in cors_allowed_methods if method.strip()]

    # Parse allowed headers
    cors_allowed_headers = os.getenv("CORS_ALLOWED_HEADERS", "Content-Type,Authorization,Consent-JWT,Consent-Id").split(",")
    cors_allowed_headers = [header.strip() for header in cors_allowed_headers if header.strip()]

    return cors_allowed_origins, cors_allowed_methods, cors_allowed_headers


def setup_auth() -> AuthConfig:
    """
    Configure and return authentication strategies.
    
    Currently only OBP consent authentication is supported.
    
    Returns:
        Configured AuthConfig instance
    """
    auth_config = AuthConfig()
    auth_config.register_auth_strategy("obp_consent_id", OBPConsentAuth())
    logger.info("Authentication configured with OBP consent strategy")
    return auth_config


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the application.
    
    Sets up:
    - Rate limiter with user-based key function
    - Exception handlers for rate limit violations
    - ValueError handler as fallback for internal slowapi/limits errors
    
    Args:
        app: FastAPI application instance
    """
    limiter = create_limiter(key_func=get_user_id_from_request)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(ValueError, _rate_limit_exceeded_handler)
    logger.info("Rate limiting configured")


def get_obp_base_url() -> str | None:
    """
    Get the OBP base URL from environment variables.
    
    Returns:
        OBP base URL or None if not set
    """
    return os.getenv('OBP_BASE_URL')


__all__ = [
    'get_cors_config',
    'setup_auth',
    'setup_rate_limiting',
    'get_obp_base_url',
]
