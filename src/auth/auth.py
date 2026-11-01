import jwt
from jwt import PyJWKClient
import os
import requests
import logging
import aiohttp
import json
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
    
    def construct_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """
        Constructs the nessecary HTTP auth headers for a given auth method
        """
        raise NotImplementedError
    
    # Asynchronous method to check if the token is valid
    async def acheck_auth(self, token: Optional[str] = None) -> bool:
        raise NotImplementedError
    
    async def get_current_user(self, token: Optional[str] = None) -> Optional[dict]:
        """
        Retrieve the current user ID associated with the provided token.
        """
        raise NotImplementedError
    

class AuthConfig:
    # This class is used to store different types of authentication methods


    def __init__(self):
        self.auth_strategies: Dict['str', BaseAuth] = {}

    def register_auth_strategy(self, name: str, auth_strategy: BaseAuth):
        """
        Register a new authentication strategy.
        
        Args:
            name (str): The name of the authentication strategy.
            auth_strategy (BaseAuth): An instance of a class that inherits from BaseAuth.
        """
        if not isinstance(auth_strategy, BaseAuth):
            raise TypeError(f"{name} must be an instance of BaseAuth")
        self.auth_strategies[name] = auth_strategy

    
class OBPConsentAuth(BaseAuth):
    def __init__(self, consent_id: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load the base URI and consumer key from the environment variables
        self.base_uri = os.getenv('OBP_BASE_URL')
        if not self.base_uri:
            raise ValueError('OBP_BASE_URL not set in environment variables')

        self.token = consent_id if consent_id else None
        
        # Get the consumer key from the environment variables
        self.opey_consumer_key = os.getenv('OBP_CONSUMER_KEY')
        if not self.opey_consumer_key:
            raise ValueError('OBP_CONSUMER_KEY not set in environment variables')
        
        version = os.getenv('OBP_API_VERSION')
        if not version:
            raise ValueError('OBP_API_VERSION not set in environment variables')
        
        self.current_user_url = self.base_uri + f'/obp/{version}/users/current'
        
        self.current_user_id = None

    async def acheck_auth(self, token: str | None = None) -> bool:
        """
        Asynchronously verifies the authentication of a user by checking the validity of a consent JWT against the OBP API.
        This function makes a GET request to the current user endpoint with the consent JWT and consumer key in the headers.
        Args:
            token (str): The consentID received from the Open Banking Project API.
            Consent should be in the 'ACCEPTED' state.
        Returns:
            bool: True if the authentication check was successful (200 status code), False otherwise.
        Raises:
            No exceptions are explicitly raised, but network-related exceptions from the requests 
            library may occur during the API call.
        """
        if not token and not self.token:
            raise ValueError('Consent ID is required')
        
        if not token:
            token = self.token
        
        assert token is not None  # Type narrowing for type checker

        headers = self.construct_headers(token)

        # DEBUG: Log consent validation attempt
        masked_token = f"{token[:20]}...{token[-10:]}" if len(token) > 30 else token[:10] + "..." if len(token) > 10 else token
        masked_consumer_key = f"{self.opey_consumer_key[:5]}...{self.opey_consumer_key[-5:]}" if self.opey_consumer_key and len(self.opey_consumer_key) > 10 else self.opey_consumer_key
        logger.debug(f"OBP consent validation - URL: {self.current_user_url}")
        logger.debug(f"OBP consent validation - Headers (masked): {{'Consent-Id': '{masked_token}', 'Consumer-Key': '{masked_consumer_key}'}}")

        client = await self.get_client()
        async with client.get(self.current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'OBP consent check successful: {response_data}')
                logger.debug(f"OBP consent validation successful - Response headers: {dict(response.headers)}")
                logger.debug(f"OBP consent validation successful - Full response: {response_data}")
                return True
            else:
                error_text = await response.read()
                logger.error(f'Error checking OBP consent by consent ID: {error_text}')
                logger.debug(f"OBP consent validation failed - Status: {response.status}")
                logger.debug(f"OBP consent validation failed - Response headers: {dict(response.headers)}")
                logger.debug(f"OBP consent validation failed - Error details: {error_text}")
                return False
    
    def construct_headers(self, token: str | None = None) -> Dict[str, str]:
        
        if not token and not self.token:
            raise ValueError('Token is required')
        
        if not token:
            token = self.token
        
        assert token is not None  # Type narrowing for type checker
        
        consumer_key = os.getenv('OBP_CONSUMER_KEY')
        if not consumer_key:
            raise ValueError('OBP_CONSUMER_KEY not set in environment variables')

        headers = {
            'Consent-Id': token,
            'Consumer-Key': consumer_key,
        }

        # DEBUG: Log header construction
        masked_token = f"{token[:20]}...{token[-10:]}" if len(token) > 30 else token[:10] + "..." if len(token) > 10 else token
        masked_consumer_key = f"{self.opey_consumer_key[:5]}...{self.opey_consumer_key[-5:]}" if self.opey_consumer_key and len(self.opey_consumer_key) > 10 else self.opey_consumer_key
        logger.debug(f"OBPConsentAuth headers constructed - Consumer-Key: {masked_consumer_key}")
        logger.debug(f"OBPConsentAuth headers constructed - Token length: {len(token)} chars, masked: {masked_token}")

        return headers
    
    async def get_current_user(self, token: str | None = None) -> Optional[dict]:
        """
        Asynchronously retrieves the current user ID associated with the provided consent token.
        
        Args:
            token (str): The consent ID token used for authentication.
        
        Returns:
            Optional[str]: The user ID if retrieval is successful, None otherwise.
        """
        if not token and not self.token:
            raise ValueError('Consent ID is required')
        
        if not token:
            token = self.token
        
        assert token is not None  # Type narrowing for type checker

        headers = self.construct_headers(token)

        client = await self.get_client()
        async with client.get(self.current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'Current user retrieved successfully: {response_data}')
                return response_data
            else:
                error_text = await response.read()
                logger.error(f'Error retrieving current user ID: {error_text}')
                return None

class OBPBearerAuth(BaseAuth):
    def __init__(self, bearer_token: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.base_uri = os.getenv('OBP_BASE_URL')
        if not self.base_uri:
            raise ValueError('OBP_BASE_URL not set in environment variables')

        self.token = bearer_token

        version = os.getenv('OBP_API_VERSION')
        if not version:
            raise ValueError('OBP_API_VERSION not set in environment variables')

        self.current_user_url = self.base_uri + f'/obp/{version}/users/current'

    def construct_headers(self, token: str | None = None) -> Dict[str, str]:
        if not token and not self.token:
            raise ValueError('Bearer token is required')

        if not token:
            token = self.token

        assert token is not None

        return {'Authorization': f'Bearer {token}'}

    async def acheck_auth(self, token: str | None = None) -> bool:
        if not token and not self.token:
            raise ValueError('Bearer token is required')

        if not token:
            token = self.token

        assert token is not None

        headers = self.construct_headers(token)

        masked_token = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else token[:5] + "..."
        logger.debug(f"OBP bearer validation - URL: {self.current_user_url}")
        logger.debug(f"OBP bearer validation - Token (masked): {masked_token}")

        client = await self.get_client()
        async with client.get(self.current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'OBP bearer check successful: {response_data.get("user_id", "unknown")}')
                return True
            else:
                error_text = await response.read()
                logger.error(f'Error checking OBP bearer token: {error_text}')
                logger.debug(f"OBP bearer validation failed - Status: {response.status}")
                return False

    async def get_current_user(self, token: str | None = None) -> Optional[dict]:
        if not token and not self.token:
            raise ValueError('Bearer token is required')

        if not token:
            token = self.token

        assert token is not None

        headers = self.construct_headers(token)

        client = await self.get_client()
        async with client.get(self.current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'Current user retrieved successfully via bearer token: {response_data}')
                return response_data
            else:
                error_text = await response.read()
                logger.error(f'Error retrieving current user via bearer token: {error_text}')
                return None
