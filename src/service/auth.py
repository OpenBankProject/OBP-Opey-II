import jwt
from jwt import PyJWKClient
import os
import requests
import logging
from typing import Dict

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

class BaseAuth():
    def __init__(self):
        self.base_uri = os.getenv('OBP_BASE_URL')
        if not self.base_uri:
            raise ValueError('OBP_BASE_URL not set in environment variables')

    # Asynchronous method to check if the token is valid
    async def acheck_auth(self, token: str) -> bool:
        raise NotImplementedError
    

class AuthTypes:
    # This class is used to store different types of authentication methods
    def __init__(self, auth_types: Dict[str, BaseAuth]):
        for key, value in auth_types.items():
            setattr(self, key, value)

class OBPConsentAuth(BaseAuth):

    def __init__(self):
        super().__init__()

        self.opey_consumer_key = os.getenv('OBP_CONSUMER_KEY')
        if not self.opey_consumer_key:
            raise ValueError('OBP_CONSUMER_KEY not set in environment variables')
        
        self.current_user_url = self.base_uri + '/obp/v5.1.0/users/current' # type: ignore


    # Asynchronous method to check if the token is valid

    async def acheck_auth(self, obp_consent_jwt: str) -> bool:
        """
        Asynchronously verifies the authentication of a user by checking the validity of a consent JWT against the OBP API.
        This function makes a GET request to the current user endpoint with the consent JWT and consumer key in the headers.
        Args:
            obp_consent_jwt (str): The consent JSON Web Token received from the Open Banking Project API.
            It should be in the 'ACCEPTED' state.
        Returns:
            bool: True if the authentication check was successful (200 status code), False otherwise.
        Raises:
            No exceptions are explicitly raised, but network-related exceptions from the requests 
            library may occur during the API call.
        """

        consumer_key = self.opey_consumer_key
        headers = {
            'Consent-JWT': obp_consent_jwt,
            'Consumer-Key': consumer_key,
        }

        response = requests.get(self.current_user_url, headers=headers)
        
        if response.status_code == 200:
            logger.debug(f'OBP consent check successful: {await response.json()}')
            return True
        else:
            logger.error(f'Error checking OBP consent: {response.text}')
            return False
