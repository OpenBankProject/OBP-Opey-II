import jwt
from jwt import PyJWKClient
import os
import requests
import logging
import aiohttp
from typing import Dict, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger('__main__.' + __name__)

class BaseAuth():
    def __init__(self, async_requests_client: Optional[aiohttp.ClientSession] = None):
        """
        Initialize the authentication service with an aiohttp ClientSession.

        This constructor sets up the authentication service with a client session for making
        asynchronous HTTP requests.

        Args:
            async_requests_client (aiohttp.ClientSession): An instance of aiohttp.ClientSession
                to be used for making asynchronous HTTP requests to the API.
        """
        self.async_requests_client = async_requests_client

    async def get_client(self):
        if not self.async_requests_client:
            self.async_requests_client = aiohttp.ClientSession()
        return self.async_requests_client
    
    # Asynchronous method to check if the token is valid
    async def acheck_auth(self, token: str) -> bool:
        raise NotImplementedError
    

class OBPConsentAuth(BaseAuth):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load the base URI and consumer key from the environment variables
        self.base_uri = os.getenv('OBP_BASE_URL')
        if not self.base_uri:
            raise ValueError('OBP_BASE_URL not set in environment variables')

        # Get the consumer key from the environment variables
        self.opey_consumer_key = os.getenv('OBP_CONSUMER_KEY')
        if not self.opey_consumer_key:
            raise ValueError('OBP_CONSUMER_KEY not set in environment variables')
        
        self.current_user_url = self.base_uri + '/obp/v5.1.0/users/current' # type: ignore

    # Asynchronous method to check if the token is valid
    async def acheck_auth(self, token: str) -> bool:
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
            'Consent-JWT': token,
            'Consumer-Key': consumer_key,
        }

        client = await self.get_client()
        async with client.get(self.current_user_url, headers=headers) as response:
            if response.status == 200:
                logger.info(f'OBP consent check successful: {await response.json()}')
                return True
            else:
                logger.error(f'Error checking OBP consent: {await response.text()}')
                return False


class AuthTypes:
    # This class is used to store different types of authentication methods
    def __init__(self, auth_types: Dict[str, BaseAuth]):
        for key, value in auth_types.items():
            setattr(self, key, value)