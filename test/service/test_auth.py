from auth.auth import OBPConsentAuth
from utils.obp_utils import sync_obp_requests, async_obp_requests
import requests
import os
from dotenv import load_dotenv
import pytest
import pytest_asyncio
import json
import aiohttp
import logging

load_dotenv()

# Configure logging to show INFO messages
logging.basicConfig(level=logging.INFO)


@pytest_asyncio.fixture
async def get_obp_consent():

    consumer_id = os.getenv("OBP_CONSUMER_ID")
    print("Consumer ID:", consumer_id)  

    consent_body = {
        "everything": True,
        "entitlements": [],
        "views": [],
        "consumer_id": consumer_id # set consumer ID to Opey Consumer ID
    }

    print("Consent Body:", consent_body)

    consent_response = await async_obp_requests("POST", "/obp/v5.1.0/my/consents/IMPLICIT", json.dumps(consent_body), consumer_key=os.getenv("API_EXPLORER_CONSUMER_KEY"))
    if not consent_response:
        raise ValueError(f"Error fetching consent from OBP")
    consent = await consent_response.json()

    return consent.get("jwt")



@pytest_asyncio.fixture
async def get_obp_auth():

    client = aiohttp.ClientSession()

    auth = OBPConsentAuth(client)

    yield auth

    # Close the client session after the tests
    await client.close()

@pytest.mark.asyncio
async def test_check_obp_consent(get_obp_consent, get_obp_auth, caplog):
    caplog.set_level(logging.INFO)
    token = get_obp_consent
    obp_consent_auth = get_obp_auth

    valid = await obp_consent_auth.acheck_auth(token)
    assert valid == True