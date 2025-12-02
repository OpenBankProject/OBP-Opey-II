from typing import Generic, Dict, Type
from fastapi_sessions.backends.session_backend import (
    BackendError,
    SessionBackend,
    SessionModel,
)
import redis.asyncio as aioredis
from redis import RedisError, ConnectionError as RedisConnectionError
from pydantic import ValidationError
import logging
from fastapi_sessions.frontends.session_frontend import ID

logger = logging.getLogger(__name__)

class RedisBackend(Generic[ID, SessionModel], SessionBackend[ID, SessionModel]):
    def __init__(self, redis_client: aioredis.Redis, session_model: Type[SessionModel]): 
        """Initialize the Redis backend with an async Redis client."""
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
            # Convert booleans and other non-primitive types to strings for Redis
            # Note: Check bool BEFORE int since bool is a subclass of int in Python
            redis_data = {
                k: str(v) if isinstance(v, bool) else v if isinstance(v, (str, int, float)) else str(v)
                for k, v in session_data.items()
            }
            await self.redis_client.hset(str(session_id), mapping=redis_data)  # type: ignore[misc]
            logger.debug(f"Session {session_id} created successfully")
        except (RedisError, ValidationError, ValueError) as e:
            self._handle_redis_error("session creation", session_id, e)
        except Exception as e:
            self._handle_redis_error("session creation", session_id, e)

    async def update(self, session_id: ID, data: SessionModel) -> None:
        try:
            existing_session_data_dict = await self.redis_client.hgetall(str(session_id))  # type: ignore[misc]

            if not existing_session_data_dict:
                raise BackendError("Session does not exist, cannot update")
            
            try:
                existing_session_data = self.session_model.model_validate(existing_session_data_dict)
            except ValidationError as e:
                logger.error(f"Invalid session data found for session {session_id}: {e}")
                raise BackendError("Corrupted session data found")

            update_data = data.model_copy(deep=True).model_dump()
            overwritten = existing_session_data.model_copy(deep=True, update=update_data)

            # Convert booleans and other non-primitive types to strings for Redis
            # Note: Check bool BEFORE int since bool is a subclass of int in Python
            redis_data = {
                k: str(v) if isinstance(v, bool) else v if isinstance(v, (str, int, float)) else str(v)
                for k, v in overwritten.model_dump().items()
            }
            await self.redis_client.hset(str(session_id), mapping=redis_data)  # type: ignore[misc]
            logger.debug(f"Session {session_id} updated successfully")
            
        except BackendError:
            raise
        except (RedisError, ValidationError, ValueError) as e:
            self._handle_redis_error("session update", session_id, e)
        except Exception as e:
            self._handle_redis_error("session update", session_id, e)

    async def read(self, session_id: ID) -> SessionModel:
        try:
            session_data = await self.redis_client.hgetall(str(session_id))  # type: ignore[misc]
            
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
            raise  # Never reached, but helps type checker
        except Exception as e:
            self._handle_redis_error("session read", session_id, e)
            raise  # Never reached, but helps type checker
    
    async def delete(self, session_id: ID) -> None:
        try:
            if not await self.redis_client.exists(str(session_id)):
                raise BackendError("Session does not exist, cannot delete")
            
            deleted_count = await self.redis_client.delete(str(session_id))
            
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