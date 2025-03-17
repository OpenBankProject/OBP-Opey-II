from service.auth import OBPConsentAuth
from utils.obp_utils import obp_requests
import requests
import os
from dotenv import load_dotenv
import pytest
import pytest_asyncio
import json

load_dotenv()



@pytest_asyncio.fixture
async def get_obp_jwt():

    consumer_id = os.getenv("OBP_CONSUMER_ID")
    print("Consumer ID:", consumer_id)  

    consent_body = {
        "everything": True,
        "entitlements": [],
        "views": [],
        "consumer_id": consumer_id # set consumer ID to Opey Consumer ID
    }

    print("Consent Body:", consent_body)

    consent_response = await obp_requests("POST", "/obp/v5.1.0/my/consents/IMPLICIT", json.dumps(consent_body), consumer_key=os.getenv("API_EXPLORER_CONSUMER_KEY"))
    if not consent_response:
        raise ValueError(f"Error fetching consent from OBP")
    consent = await consent_response.json()

    return consent.get("jwt")

@pytest_asyncio.fixture
def get_obp_auth():
    return OBPConsentAuth()

@pytest.mark.asyncio
async def test_check_obp_consent(get_obp_jwt, get_obp_auth):
    token = get_obp_jwt
    obp_consent_auth = get_obp_auth

    valid = await obp_consent_auth.acheck_auth(token)
    assert valid == True