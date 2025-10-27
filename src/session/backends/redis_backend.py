from typing import Generic, Dict, Type
from fastapi_sessions.backends.session_backend import (
    BackendError,
    SessionBackend,
    SessionModel,
)
from redis import Redis, RedisError, ConnectionError as RedisConnectionError
from pydantic import ValidationError
import logging
from fastapi_sessions.frontends.session_frontend import ID

logger = logging.getLogger(__name__)

class RedisBackend(Generic[ID, SessionModel], SessionBackend[ID, SessionModel]):
    def __init__(self, redis_client: Redis, session_model: Type[SessionModel]): 
        """Initialize the Redis backend with a Redis client."""
        self.redis_client = redis_client
        self.session_model = session_model

    def _handle_redis_error(self, operation: str, session_id: ID, error: Exception) -> None:
        """Centralized error handling for Redis operations."""
        if isinstance(error, RedisConnectionError):
            logger.error(f"Redis connection failed during {operation} for session {session_id}: {error}")
            raise BackendError(f"Database connection error during {operation}")
        elif isinstance(error, RedisError):
            logger.error(f"Redis error during {operation} for session {session_id}: {error}")
            raise BackendError(f"Database error during {operation}")
        else:
            logger.error(f"Unexpected error during {operation} for session {session_id}: {error}")
            raise BackendError(f"Unexpected error during {operation}")

    async def create(self, session_id: ID, data: SessionModel) -> None:
        try:
            session_data = data.model_copy(deep=True).model_dump()
            self.redis_client.hset(str(session_id), mapping=session_data)
            logger.debug(f"Session {session_id} created successfully")
        except (RedisError, ValidationError, ValueError) as e:
            self._handle_redis_error("session creation", session_id, e)
        except Exception as e:
            self._handle_redis_error("session creation", session_id, e)

    async def update(self, session_id: ID, data: SessionModel) -> None:
        try:
            existing_session_data_dict = self.redis_client.hgetall(str(session_id))

            if not existing_session_data_dict:
                raise BackendError("Session does not exist, cannot update")
            
            try:
                existing_session_data = self.session_model.model_validate(existing_session_data_dict)
            except ValidationError as e:
                logger.error(f"Invalid session data found for session {session_id}: {e}")
                raise BackendError("Corrupted session data found")

            update_data = data.model_copy(deep=True).model_dump()
            overwritten = existing_session_data.model_copy(deep=True, update=update_data)

            self.redis_client.hset(str(session_id), mapping=overwritten.model_dump())
            logger.debug(f"Session {session_id} updated successfully")
            
        except BackendError:
            raise
        except (RedisError, ValidationError, ValueError) as e:
            self._handle_redis_error("session update", session_id, e)
        except Exception as e:
            self._handle_redis_error("session update", session_id, e)

    async def read(self, session_id: ID) -> SessionModel:
        try:
            session_data = self.redis_client.hgetall(str(session_id))
            
            if not session_data:
                raise BackendError("Session not found")
            
            try:
                return self.session_model.model_validate(session_data)
            except ValidationError as e:
                logger.error(f"Invalid session data format for session {session_id}: {e}")
                raise BackendError("Corrupted session data")
                
        except BackendError:
            raise
        except (RedisError, ValidationError) as e:
            self._handle_redis_error("session read", session_id, e)
        except Exception as e:
            self._handle_redis_error("session read", session_id, e)
    
    async def delete(self, session_id: ID) -> None:
        try:
            if not self.redis_client.exists(str(session_id)):
                raise BackendError("Session does not exist, cannot delete")
            
            deleted_count = self.redis_client.delete(str(session_id))
            
            if deleted_count == 0:
                logger.warning(f"Session {session_id} was not deleted, may have been removed concurrently")
            else:
                logger.debug(f"Session {session_id} deleted successfully")
                
        except BackendError:
            raise
        except (RedisError, ValueError) as e:
            self._handle_redis_error("session deletion", session_id, e)
        except Exception as e:
            self._handle_redis_error("session deletion", session_id, e)