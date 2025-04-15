from service.service import app
from httpx import AsyncClient
import pytest
import pytest_asyncio
from utils.obp_utils import sync_obp_requests
import os
import json


@pytest.fixture
def get_obp_consent():

    consumer_id = os.getenv("OBP_CONSUMER_ID")
    print("Consumer ID:", consumer_id)  

    consent_body = {
        "everything": True,
        "entitlements": [],
        "views": [],
        "consumer_id": consumer_id # set consumer ID to Opey Consumer ID
    }

    print("Consent Body:", consent_body)

    consent_response = sync_obp_requests("POST", "/obp/v5.1.0/my/consents/IMPLICIT", json.dumps(consent_body), consumer_key=os.getenv("API_EXPLORER_CONSUMER_KEY"))
    if not consent_response:
        raise ValueError(f"Error fetching consent from OBP")
    consent = consent_response.json()

    return consent.get("jwt")


@pytest_asyncio.fixture(loop_scope="session")
async def create_session(client: AsyncClient, get_obp_consent):
    """
    Used for creating a session in the subsequent tests. NOT for testing the session creation endpoint itself.
    """
    consent_jwt = get_obp_consent
    response = await client.post("/create-session", headers={'Consent-JWT': consent_jwt})

    return response.cookies.get("session")


@pytest.mark.asyncio(loop_scope="session")
async def test_create_session_incorrect_format(client: AsyncClient):
    response = await client.post("/create-session", headers={'Consent-JWT': 'test-jwt'})
    assert response.status_code == 401    


@pytest.mark.dependency()
@pytest.mark.asyncio(loop_scope="session")
async def test_create_session(client: AsyncClient, get_obp_consent):
    consent_jwt = get_obp_consent
    response = await client.post("/create-session", headers={'Consent-JWT': consent_jwt})
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
        json={'message': 'Hello opey.', 'thread_id': '12345', 'is_tool_call_approval': False},
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


