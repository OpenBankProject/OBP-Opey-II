from typing import Generic, Dict, Type
from fastapi_sessions.backends.session_backend import (
    BackendError,
    SessionBackend,
    SessionModel,
)
from redis import Redis
from fastapi_sessions.frontends.session_frontend import ID

class RedisBackend(Generic[ID, SessionModel], SessionBackend[ID, SessionModel]):
    def __init__(self, redis_client: Redis, session_model: Type[SessionModel]): 
        """Initialize the Redis backend with a Redis client."""
        self.redis_client = redis_client
        self.session_model = session_model

    async def create(self, session_id: ID, data: SessionModel) -> None:
        self.redis_client.hset(str(session_id), mapping=data.model_copy(deep=True).model_dump())

    async def update(self, session_id: ID, data: SessionModel) -> None:
        # We need to retrieve the existing session data, then pass the updates
        existing_session_data_dict = self.redis_client.hgetall(str(session_id))

        if not existing_session_data_dict:
            raise BackendError("Session does not exist, cannot update")
        
        existing_session_data = self.session_model.model_validate(existing_session_data_dict)
        overwritten = existing_session_data.model_copy(deep=True, update=data.model_copy(deep=True).model_dump())

        # Update the session data in Redis
        self.redis_client.hset(str(session_id), mapping=overwritten.model_dump())

    async def read(self, session_id: ID) -> SessionModel:
        session_data = self.redis_client.hgetall(str(session_id))
        if not session_data:
            raise BackendError("Session not found")
        return self.session_model.model_validate(session_data)
    
    async def delete(self, session_id: ID) -> None:
        if not self.redis_client.exists(str(session_id)):
            raise BackendError("Session does not exist, cannot delete")
        self.redis_client.delete(str(session_id))