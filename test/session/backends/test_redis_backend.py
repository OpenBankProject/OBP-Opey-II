import pytest
import pytest_asyncio
from pydantic import BaseModel
from src.session.backends.redis_backend import RedisBackend
from fastapi_sessions.backends.session_backend import BackendError
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

@pytest.mark.asyncio
async def test_redis_backend_create():
    redis_client = Mock()
    session_model = Mock
    backend = RedisBackend[UUID, session_model](redis_client, session_model)

    session_id = uuid4()
    session_data = Mock()

    await backend.create(session_id, session_data)

    redis_client.hset.assert_called_once_with(str(session_id), mapping=session_data.model_copy(deep=True).model_dump())

@pytest.mark.asyncio
async def test_redis_backend_read():
    redis_client = Mock()
    session_model = Mock
    session_model.model_validate = Mock(return_value=session_model)
    backend = RedisBackend[UUID, session_model](redis_client, session_model)

    session_id = uuid4()
    session_data_dict = {'key': 'value'}
    redis_client.hgetall.return_value = session_data_dict

    result = await backend.read(session_id)

    redis_client.hgetall.assert_called_once_with(str(session_id))
    assert result == session_model.model_validate(session_data_dict)

@pytest.mark.asyncio
async def test_redis_backend_read_not_found():
    redis_client = Mock()
    session_model = Mock
    backend = RedisBackend[UUID, session_model](redis_client, session_model)

    session_id = uuid4()
    redis_client.hgetall.return_value = {}

    with pytest.raises(BackendError, match="Session not found"):
        await backend.read(session_id)


@pytest.mark.asyncio
async def test_redis_backend_update():
    redis_client = Mock()
    class SessionModel(BaseModel):
        key: str

    backend = RedisBackend[UUID, SessionModel](redis_client, SessionModel)

    session_id = uuid4()
    session_id = uuid4()
    existing_session_data_dict = {'key': 'value'}
    redis_client.hgetall.return_value = existing_session_data_dict
    overwrite_session_data = SessionModel(key='new_value')

    await backend.update(session_id, overwrite_session_data)

    redis_client.hgetall.assert_called_once_with(str(session_id))
    redis_client.hset.assert_called_once_with(str(session_id), mapping=overwrite_session_data.model_copy(deep=True).model_dump())

@pytest.mark.asyncio
async def test_redis_backend_update_not_found():
    redis_client = Mock()
    class SessionModel(BaseModel):
        key: str
    backend = RedisBackend[UUID, SessionModel](redis_client, SessionModel)

    session_id = uuid4()
    redis_client.hgetall.return_value = {}

    with pytest.raises(BackendError, match="Session does not exist, cannot update"):
        await backend.update(session_id, SessionModel(key='new_value'))


@pytest.mark.asyncio
async def test_redis_backend_delete():
    redis_client = Mock()
    session_model = Mock
    backend = RedisBackend[UUID, session_model](redis_client, session_model)

    session_id = uuid4()
    redis_client.exists.return_value = True

    await backend.delete(session_id)

    redis_client.exists.assert_called_once_with(str(session_id))
    redis_client.delete.assert_called_once_with(str(session_id))