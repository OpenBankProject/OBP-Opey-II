import os
import logging
from typing import Optional
from fastapi import HTTPException
from auth.session import SessionData

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('opey.usage_tracker')

class UsageTracker:
    """
    Tracks token and request usage for anonymous sessions and enforces limits.
    """

    def __init__(self):
        self.anonymous_token_limit = int(os.getenv("ANONYMOUS_SESSION_TOKEN_LIMIT", 10000))
        self.anonymous_request_limit = int(os.getenv("ANONYMOUS_SESSION_REQUEST_LIMIT", 20))
        self.allow_anonymous = os.getenv("ALLOW_ANONYMOUS_SESSIONS", "false").lower() == "true"

    def check_anonymous_limits(self, session_data: SessionData) -> None:
        """
        Check if an anonymous session has exceeded its usage limits.

        Args:
            session_data: The session data to check

        Raises:
            HTTPException: If the session has exceeded its limits
        """
        if not session_data.is_anonymous:
            return

        if session_data.token_usage >= self.anonymous_token_limit:
            logger.warning(f"Anonymous session exceeded token limit: {session_data.token_usage}/{self.anonymous_token_limit}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Token limit exceeded",
                    "message": f"Anonymous sessions are limited to {self.anonymous_token_limit} tokens. Please authenticate to continue.",
                    "usage": {
                        "tokens_used": session_data.token_usage,
                        "token_limit": self.anonymous_token_limit,
                        "requests_made": session_data.request_count,
                        "request_limit": self.anonymous_request_limit
                    }
                }
            )

        if session_data.request_count >= self.anonymous_request_limit:
            logger.warning(f"Anonymous session exceeded request limit: {session_data.request_count}/{self.anonymous_request_limit}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Request limit exceeded",
                    "message": f"Anonymous sessions are limited to {self.anonymous_request_limit} requests. Please authenticate to continue.",
                    "usage": {
                        "tokens_used": session_data.token_usage,
                        "token_limit": self.anonymous_token_limit,
                        "requests_made": session_data.request_count,
                        "request_limit": self.anonymous_request_limit
                    }
                }
            )

    def update_token_usage(self, session_data: SessionData, token_count: int) -> SessionData:
        """
        Update token usage for a session.

        Args:
            session_data: The session data to update
            token_count: Number of tokens to add to the usage

        Returns:
            Updated session data
        """
        if session_data.is_anonymous:
            session_data.token_usage += token_count
            logger.debug(f"Anonymous session token usage: {session_data.token_usage}/{self.anonymous_token_limit}")

        return session_data

    def update_request_count(self, session_data: SessionData) -> SessionData:
        """
        Update request count for a session.

        Args:
            session_data: The session data to update

        Returns:
            Updated session data
        """
        if session_data.is_anonymous:
            session_data.request_count += 1
            logger.debug(f"Anonymous session request count: {session_data.request_count}/{self.anonymous_request_limit}")

        return session_data

    def get_usage_info(self, session_data: SessionData) -> dict:
        """
        Get usage information for a session.

        Args:
            session_data: The session data to get info for

        Returns:
            Dictionary containing usage information
        """
        if not session_data.is_anonymous:
            return {
                "session_type": "authenticated",
                "unlimited_usage": True
            }

        return {
            "session_type": "anonymous",
            "tokens_used": session_data.token_usage,
            "token_limit": self.anonymous_token_limit,
            "tokens_remaining": max(0, self.anonymous_token_limit - session_data.token_usage),
            "requests_made": session_data.request_count,
            "request_limit": self.anonymous_request_limit,
            "requests_remaining": max(0, self.anonymous_request_limit - session_data.request_count),
            "approaching_token_limit": session_data.token_usage >= (self.anonymous_token_limit * 0.8),
            "approaching_request_limit": session_data.request_count >= (self.anonymous_request_limit * 0.8)
        }

# Global usage tracker instance
usage_tracker = UsageTracker()
