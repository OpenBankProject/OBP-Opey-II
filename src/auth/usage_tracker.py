import os
import logging
from typing import Optional
from abc import ABC, abstractmethod
from pydantic import BaseModel
from fastapi import HTTPException
from auth.session import SessionData

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('opey.usage_tracker')

class IUsageTracker(ABC):

    @abstractmethod
    def check_limits(self, session_data: SessionData) -> None:
        """
        Check if the session has exceeded its usage limits.
        
        Args:
            session_data: The session data to check
        
        Raises:
            HTTPException: If the session has exceeded its limits
        """
        pass

    @abstractmethod
    def update_token_usage(self, session_data: SessionData, token_count: int) -> None:
        """
        Update token usage for a session.
        
        Args:
            session_data: The session data to update
            token_count: Number of tokens to add to the usage
        
        Returns:
            Updated session data
        """
        pass

    @abstractmethod
    def update_request_count(self, session_data: SessionData) -> None:
        """
        Update request count for a session.
        
        Args:
            session_data: The session data to update
        
        Returns:
            Updated session data
        """
        pass


class AnonymousUsageTracker(IUsageTracker):
    """
    Tracks token and request usage for anonymous sessions and enforces limits.
    """

    def __init__(self):
        self.anonymous_token_limit = int(os.getenv("ANONYMOUS_SESSION_TOKEN_LIMIT", 10000))
        self.anonymous_request_limit = int(os.getenv("ANONYMOUS_SESSION_REQUEST_LIMIT", 20))
        self.allow_anonymous = os.getenv("ALLOW_ANONYMOUS_SESSIONS", "false").lower() == "true"

    def check_limits(self, session_data: SessionData) -> None:
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

    def update_token_usage(self, session_data: SessionData, token_count: int) -> None:
        if session_data.is_anonymous:
            session_data.token_usage += token_count
            logger.debug(f"Anonymous session token usage: {session_data.token_usage}/{self.anonymous_token_limit}")

    def update_request_count(self, session_data: SessionData) -> None:
        if session_data.is_anonymous:
            session_data.request_count += 1

usage_tracker = AnonymousUsageTracker()