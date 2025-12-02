from service.service import app
from httpx import AsyncClient
import pytest
import pytest_asyncio
from utils.obp_utils import sync_obp_requests
import os
import json


@pytest_asyncio.fixture(loop_scope="session")
async def create_session(client: AsyncClient, get_obp_consent):
    """
    Used for creating a session in the subsequent tests. NOT for testing the session creation endpoint itself.
    """
    consent_id = get_obp_consent
    response = await client.post("/create-session", headers={'Consent-JWT': consent_id})

    return response.cookies.get("session")


@pytest.mark.asyncio(loop_scope="session")
async def test_create_session_incorrect_format(client: AsyncClient):
    response = await client.post("/create-session", headers={'Consent-JWT': 'test-jwt'})
    assert response.status_code == 401    


@pytest.mark.dependency()
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skip("Requires valid OBP JWT token - run with real credentials to test")
async def test_create_session(client: AsyncClient, get_obp_consent):
    consent_id = get_obp_consent
    response = await client.post("/create-session", headers={'Consent-JWT': consent_id})
    print("Cookies:", response.cookies)
    assert response.status_code == 200
    assert "session" in response.cookies
    assert response.text == "session created"


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.dependency(depends=["test_create_session"])
async def test_get_protected_route(client: AsyncClient,):

    # Try to access the protected route
    response = await client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
@pytest.mark.skip("Streaming endpoints are difficult to test cleanly")
async def test_get_protected_streaming_route(client: AsyncClient, create_session, mocker):
    # Create a session first
    session_id = create_session
    print(session_id)

    from typing import AsyncGenerator
    
    # Define your mock async generator function
    async def mock_generator(*args, **kwargs):
        yield "data: {\"content\":\"Test response\"}\n\n"
        yield "data: [DONE]\n\n"
    
    # Use the mocker fixture to patch the function
    mock = mocker.patch('service.service.opey_message_generator', return_value=mock_generator)
    
    # Test with the mock
    response = await client.post(
        "/stream", 
        json={'message': 'Hello opey.', 'thread_id': '12345', 'tool_call_approval': {'approval': 'approve', 'tool_call_id': 'call_12345'}},
        headers={'Content-Type': 'application/json'}
    )
    assert response.status_code == 200


@pytest.mark.dependency(depends=["test_create_session"])
@pytest.mark.asyncio(loop_scope="session")
async def test_delete_session(client: AsyncClient, create_session):
    # Create a session first
    session_id = create_session
    print(session_id)

    # Try to delete the session
    response = await client.post("/delete-session")
    assert response.status_code == 200
    assert response.text == "session deleted"

@pytest.mark.dependency(depends=["test_delete_session"])
@pytest.mark.asyncio(loop_scope="session")
async def test_get_protected_route_after_deletion(client: AsyncClient):
    # Try to access the protected route after session deletion
    response = await client.get("/status")
    assert response.status_code == 403
    assert response.json() == {"detail": "No session provided"}


