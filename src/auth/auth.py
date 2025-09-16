import jwt
from jwt import PyJWKClient
import os
import requests
import logging
import aiohttp
from typing import Dict, Optional

from .schema import DirectLoginConfig

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
    
    def construct_headers(self):
        """
        Constructs the nessecary HTTP auth headers for a given auth method
        """
        raise NotImplementedError
    
    # Asynchronous method to check if the token is valid
    async def acheck_auth(self, token: str) -> bool:
        raise NotImplementedError
    

class AuthConfig:
    # This class is used to store different types of authentication methods


    def __init__(self):
        self.auth_strategies = {}

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

# Define differnt auth types here
class OBPConsentAuth(BaseAuth):

    def __init__(self, consent_jwt: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load the base URI and consumer key from the environment variables
        self.base_uri = os.getenv('OBP_BASE_URL')
        if not self.base_uri:
            raise ValueError('OBP_BASE_URL not set in environment variables')

        if consent_jwt:
            self.token = consent_jwt
        # Get the consumer key from the environment variables
        self.opey_consumer_key = os.getenv('OBP_CONSUMER_KEY')
        if not self.opey_consumer_key:
            raise ValueError('OBP_CONSUMER_KEY not set in environment variables')
        
        self.current_user_url = self.base_uri + '/obp/v5.1.0/users/current' # type: ignore
 
    # Asynchronous method to check if the token is valid
    async def acheck_auth(self, token: str | None = None) -> bool:
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
        if not token and not self.token:
            raise ValueError('Token is required')
        
        if not token:
            token = self.token

        headers = self.construct_headers(token)

        # DEBUG: Log consent validation attempt
        masked_token = f"{token[:20]}...{token[-10:]}" if len(token) > 30 else token[:10] + "..." if len(token) > 10 else token
        logger.debug(f"OBP consent validation - URL: {self.current_user_url}")
        logger.debug(f"OBP consent validation - Headers (JWT masked): {{'Consent-JWT': '{masked_token}', 'Consumer-Key': '{headers.get('Consumer-Key')}'}}")

        client = await self.get_client()
        async with client.get(self.current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'OBP consent check successful: {response_data}')
                logger.debug(f"OBP consent validation successful - Response headers: {dict(response.headers)}")
                logger.debug(f"OBP consent validation successful - Full response: {response_data}")
                return True
            else:
                error_text = await response.text()
                logger.error(f'Error checking OBP consent: {error_text}')
                logger.debug(f"OBP consent validation failed - Status: {response.status}")
                logger.debug(f"OBP consent validation failed - Response headers: {dict(response.headers)}")
                logger.debug(f"OBP consent validation failed - Error details: {error_text}")
                return False
            
    def construct_headers(self, token: str | None = None) -> Dict[str, str]:
        """
        Constructs the necessary HTTP auth headers for a given auth method
        """
        if not token and not self.token:
            raise ValueError('Token is required')
        
        if not token:
            token = self.token

        headers = {
            'Consent-JWT': token,
            'Consumer-Key': os.getenv('OBP_CONSUMER_KEY'),
        }

        # DEBUG: Log header construction
        masked_token = f"{token[:20]}...{token[-10:]}" if len(token) > 30 else token[:10] + "..." if len(token) > 10 else token
        logger.debug(f"OBPConsentAuth headers constructed - Consumer-Key: {headers.get('Consumer-Key')}")
        logger.debug(f"OBPConsentAuth headers constructed - JWT length: {len(token)} chars, masked: {masked_token}")

        return headers


class OBPDirectLoginAuth(BaseAuth):

    def __init__(self, config: DirectLoginConfig = None, *args, **kwargs):
        """
        Initialize the DirectLogin authentication handler with the provided configuration.
        Parameters. Pass no config to just use the instance for checking direct login tokens you have already.
        ----------
        config : DirectLoginConfig, optional
            Configuration object containing authentication credentials and settings.
            If provided, the username, password, and consumer_key will be extracted from it.
            If config.base_uri is provided, it will be used; otherwise, OBP_BASE_URL 
            environment variable will be used.
        *args : tuple
            Variable length argument list passed to the parent class constructor.
        **kwargs : dict
            Arbitrary keyword arguments passed to the parent class constructor.
        Raises
        ------
        ValueError
            If config.base_uri is not provided and OBP_BASE_URL environment variable is not set.
        """
        super().__init__(*args, **kwargs)


        if config:
            self.username = config.username
            self.password = config.password
            self.consumer_key = config.consumer_key
            if config.base_uri:
                self.base_uri = config.base_uri
            else:
                logger.warning('No base URI provided in config, using environment variable')
                self.base_uri = os.getenv('OBP_BASE_URL')
                if not self.base_uri:
                    raise ValueError('OBP_BASE_URL not set in environment variables')
        

    async def get_direct_login_token(self) -> str:
        if self.token:
            return self.token
        

        if not self.username or not self.password or not self.consumer_key:
            raise ValueError('Username, password, and consumer key are required')

        client = await self.get_client()

        url = f"{self.base_uri}/my/logins/direct"
        headers = {
            "Content-Type": "application/json",
            "directlogin": f"username={self.username},password={self.password},consumer_key={self.consumer_key}"
        }

        async with client.post(url, headers=headers) as response:
            if response.status == 201:
                token = (await response.json()).get('token')
                logger.info("Token fetched successfully!")
                self.token = token
                return token
            else:
                logger.error("Error fetching token:", await response.text())
                return None
            

    def construct_headers(self, token: str) -> Dict[str, str]:
        """
        Constructs the necessary HTTP auth headers for a given auth method
        """
        # If the class is initialized with a config, we can use it to get the token

        if not token:
            raise ValueError('Token is required')

        headers = {
            'Authorization': f'DirectLogin token={token}',
            'Content-Type': 'application/json',
        }

        return headers
