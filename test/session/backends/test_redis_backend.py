import pytest
from pydantic import BaseModel
from src.auth.session.backends.redis_backend import RedisBackend
from fastapi_sessions.backends.session_backend import BackendError
from redis import ConnectionError as RedisConnectionError
from unittest.mock import AsyncMock
from uuid import UUID, uuid4


class SessionModel(BaseModel):
    key: str


class FlagSessionModel(BaseModel):
    key: str
    flag: bool


def backend_for(model, redis_client=None):
    """A RedisBackend over an async Redis client that records its calls and never connects."""
    redis_client = redis_client or AsyncMock()
    return RedisBackend[UUID, model](redis_client, model), redis_client


@pytest.mark.asyncio
async def test_redis_backend_create():
    backend, redis_client = backend_for(SessionModel)
    session_id = uuid4()

    await backend.create(session_id, SessionModel(key='value'))

    redis_client.hset.assert_awaited_once_with(str(session_id), mapping={'key': 'value'})


@pytest.mark.asyncio
async def test_redis_backend_create_stores_booleans_as_strings():
    backend, redis_client = backend_for(FlagSessionModel)
    session_id = uuid4()

    await backend.create(session_id, FlagSessionModel(key='value', flag=True))

    redis_client.hset.assert_awaited_once_with(str(session_id), mapping={'key': 'value', 'flag': 'True'})


@pytest.mark.asyncio
async def test_redis_backend_read():
    backend, redis_client = backend_for(SessionModel)
    session_id = uuid4()
    redis_client.hgetall.return_value = {'key': 'value'}

    result = await backend.read(session_id)

    redis_client.hgetall.assert_awaited_once_with(str(session_id))
    assert result == SessionModel(key='value')


@pytest.mark.asyncio
async def test_redis_backend_read_not_found():
    backend, redis_client = backend_for(SessionModel)
    redis_client.hgetall.return_value = {}

    with pytest.raises(BackendError, match="Session not found"):
        await backend.read(uuid4())


@pytest.mark.asyncio
async def test_redis_backend_read_corrupted_data():
    backend, redis_client = backend_for(SessionModel)
    redis_client.hgetall.return_value = {'other': 'value'}

    with pytest.raises(BackendError, match="Corrupted session data"):
        await backend.read(uuid4())


@pytest.mark.asyncio
async def test_redis_backend_update():
    backend, redis_client = backend_for(SessionModel)
    session_id = uuid4()
    redis_client.hgetall.return_value = {'key': 'value'}

    await backend.update(session_id, SessionModel(key='new_value'))

    redis_client.hgetall.assert_awaited_once_with(str(session_id))
    redis_client.hset.assert_awaited_once_with(str(session_id), mapping={'key': 'new_value'})


@pytest.mark.asyncio
async def test_redis_backend_update_not_found():
    backend, redis_client = backend_for(SessionModel)
    redis_client.hgetall.return_value = {}

    with pytest.raises(BackendError, match="Session does not exist, cannot update"):
        await backend.update(uuid4(), SessionModel(key='new_value'))


@pytest.mark.asyncio
async def test_redis_backend_delete():
    backend, redis_client = backend_for(SessionModel)
    session_id = uuid4()
    redis_client.exists.return_value = True
    redis_client.delete.return_value = 1

    await backend.delete(session_id)

    redis_client.exists.assert_awaited_once_with(str(session_id))
    redis_client.delete.assert_awaited_once_with(str(session_id))


@pytest.mark.asyncio
async def test_redis_backend_delete_not_found():
    backend, redis_client = backend_for(SessionModel)
    redis_client.exists.return_value = False

    with pytest.raises(BackendError, match="Session does not exist, cannot delete"):
        await backend.delete(uuid4())

    redis_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_backend_reports_a_lost_connection():
    backend, redis_client = backend_for(SessionModel)
    redis_client.hgetall.side_effect = RedisConnectionError("connection refused")

    with pytest.raises(BackendError, match="Database connection error during session read"):
        await backend.read(uuid4())
