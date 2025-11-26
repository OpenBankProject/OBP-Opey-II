import jwt
from jwt import PyJWKClient
import os
import requests
import logging
import aiohttp
import json
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

class OBPDirectLoginAuth(BaseAuth):

    def __init__(self, config: Optional[DirectLoginConfig] = None, *args, **kwargs):
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

        # Initialize attributes
        self.token = None
        self.username = None
        self.password = None
        self.consumer_key = None
        self.base_uri = None

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
        else:
            # When no config is provided, still need base_uri for validation
            self.base_uri = os.getenv('OBP_BASE_URL')
            if not self.base_uri:
                logger.warning('OBP_BASE_URL not set - will need to be set before using this auth')
        

    async def _get_direct_login_token(self) -> str:
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
                logger.info("DirectLogin token fetched successfully!")
                self.token = token
                return token
            else:
                error_text = await response.text()
                logger.error(f"Error fetching DirectLogin token: {error_text}")
                return ""

    async def acheck_auth(self, token: Optional[str] = None) -> bool:
        """
        Verify a DirectLogin token by making a request to the OBP API.
        
        Args:
            token (str, optional): The DirectLogin token to verify. If not provided,
                uses self.token or attempts to fetch a new token.
        
        Returns:
            bool: True if the token is valid, False otherwise.
        """
        if not token:
            if self.token:
                token = self.token
            else:
                # Try to fetch a new token if credentials are available
                if self.username and self.password and self.consumer_key:
                    token = await self._get_direct_login_token()
                    if not token:
                        return False
                else:
                    raise ValueError('Token is required or credentials must be provided')
        
        if not self.base_uri:
            raise ValueError('Base URI is required for token validation')
        
        version = os.getenv('OBP_API_VERSION', 'v6.0.0')
        current_user_url = f"{self.base_uri}/obp/{version}/users/current"
        
        headers = self.construct_headers(token)
        
        # Token is guaranteed to be a string at this point
        assert token is not None
        masked_token = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else token[:5] + "..."
        logger.debug(f"DirectLogin validation - URL: {current_user_url}")
        logger.debug(f"DirectLogin validation - Token (masked): {masked_token}")
        
        client = await self.get_client()
        async with client.get(current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'DirectLogin check successful for user: {response_data.get("user_id", "unknown")}')
                logger.debug(f"DirectLogin validation successful - Full response: {response_data}")
                return True
            else:
                error_text = await response.text()
                logger.error(f'Error checking DirectLogin token: {error_text}')
                logger.debug(f"DirectLogin validation failed - Status: {response.status}")
                logger.debug(f"DirectLogin validation failed - Error details: {error_text}")
                return False

    async def get_current_user(self, token: Optional[str] = None) -> Optional[dict]:
        """
        Retrieve the current user data associated with the provided DirectLogin token.
        
        Args:
            token: The DirectLogin token used for authentication.
        
        Returns:
            User data dict if retrieval is successful, None otherwise.
        """
        if not token:
            token = self.token
            
        if not token:
            raise ValueError('Token is required')
        
        if not self.base_uri:
            raise ValueError('Base URI is required')
        
        version = os.getenv('OBP_API_VERSION', 'v6.0.0')
        current_user_url = f"{self.base_uri}/obp/{version}/users/current"
        
        headers = self.construct_headers(token)
        
        client = await self.get_client()
        async with client.get(current_user_url, headers=headers) as response:
            if response.status == 200:
                response_data = await response.json()
                logger.info(f'Current user data retrieved successfully: {response_data}')
                return response_data
            else:
                error_text = await response.text()
                logger.error(f'Error retrieving current user data: {error_text}')
                return None

    def construct_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """
        Constructs the necessary HTTP auth headers for a given auth method
        """
        # If the class is initialized with a config, we can use it to get the token

        if not token:
            token = self.token
            
        if not token:
            raise ValueError('Token is required')

        headers = {
            'Authorization': f'DirectLogin token={token}',
            'Content-Type': 'application/json',
        }

        return headers

def _check_entitlements(entitlements_response: dict, required_entitlements: list[str]) -> tuple[bool, list[str]]:
    """
    Check if the required entitlements are present in the entitlements response.
    
    Args:
        entitlements_response: Response from /my/entitlements endpoint with format:
            {"list": [{"entitlement_id": "...", "role_name": "...", "bank_id": "..."}]}
        required_entitlements: List of required role names
    
    Returns:
        Tuple of (all_present, missing_entitlements)
    """
    if not entitlements_response or 'list' not in entitlements_response:
        return False, required_entitlements
    
    available_roles = {entitlement.get('role_name') for entitlement in entitlements_response['list']}
    missing = [role for role in required_entitlements if role not in available_roles]
    
    return len(missing) == 0, missing


async def create_admin_direct_login_auth(
    required_entitlements: Optional[list[str]] = None,
    verify_entitlements: bool = True
) -> OBPDirectLoginAuth:
    """
    Create an admin DirectLogin authentication instance with optional entitlement verification.
    
    Args:
        required_entitlements: List of required role names to verify. If None and verify_entitlements
            is True, will use a default set of common admin entitlements.
        verify_entitlements: Whether to verify the admin has the required entitlements.
    
    Returns:
        OBPDirectLoginAuth instance configured for admin use
    
    Raises:
        ValueError: If required environment variables are missing or entitlements are insufficient
    """
    # Validate environment variables
    admin_username = os.getenv('OBP_USERNAME')
    admin_password = os.getenv('OBP_PASSWORD')
    consumer_key = os.getenv('OBP_CONSUMER_KEY')
    base_uri = os.getenv('OBP_BASE_URL')
    
    if not all([admin_username, admin_password, consumer_key, base_uri]):
        missing = [
            var for var, val in [
                ('OBP_USERNAME', admin_username),
                ('OBP_PASSWORD', admin_password),
                ('OBP_CONSUMER_KEY', consumer_key),
                ('OBP_BASE_URL', base_uri)
            ] if not val
        ]
        raise ValueError(f'Missing required environment variables: {", ".join(missing)}')
    
    # Type narrowing - we've checked these are not None above
    assert admin_username is not None
    assert admin_password is not None
    assert consumer_key is not None
    assert base_uri is not None
    
    admin_direct_login_config = DirectLoginConfig(
        username=admin_username,
        password=admin_password,
        consumer_key=consumer_key,
        base_uri=base_uri
    )
    
    admin_auth = OBPDirectLoginAuth(config=admin_direct_login_config)
    
    # Verify authentication works
    if not await admin_auth.acheck_auth():
        raise ValueError('Failed to authenticate admin user with provided credentials')
    
    # Verify entitlements if requested
    if verify_entitlements:
        from client.obp_client import OBPClient
        
        obp_client = OBPClient(auth=admin_auth)
        version = os.getenv('OBP_API_VERSION', 'v6.0.0')
        
        try:
            response_json = await obp_client.async_obp_requests(
                "GET", 
                f"/obp/{version}/my/entitlements",
                ""
            )
            
            if not response_json:
                logger.warning('Failed to fetch entitlements - received empty response')
                return admin_auth
            
            # Parse the JSON string response
            entitlements_response = json.loads(response_json) if isinstance(response_json, str) else response_json
            
            # Use provided entitlements or default set
            if required_entitlements is None:
                required_entitlements = [
                    'CanCreateNonPersonalUserAttribute',
                    'CanGetNonPersonalUserAttributes',
                    'CanCreateSystemLevelDynamicEntity',
                    'CanGetSystemLevelDynamicEntities'
                ]
            
            all_present, missing = _check_entitlements(entitlements_response, required_entitlements)
            
            if not all_present:
                logger.warning(
                    f'Admin user is missing required entitlements: {", ".join(missing)}. '
                    f'This may limit functionality.'
                )
                # Don't raise, just warn - let the caller decide if this is critical
        except Exception as e:
            logger.error(f'Failed to verify admin entitlements: {e}')
            # Don't raise - auth still works, just couldn't verify entitlements
    
    return admin_auth
