from auth.auth import BaseAuth
import aiohttp
import asyncio
import os
import json
import jwt
import logging

from typing import Any, Literal
from langchain_core.tools import StructuredTool

# Configure logging
logger = logging.getLogger(__name__)


class OBPRequestsModule:
    """
    This class is for managing requests to the Open Bank Project (OBP) API.
    """
    def __init__(self, auth: BaseAuth):
        """
        Initialize the OBPRequestsModule with an authentication object.

        Args:
            auth (BaseAuth): An instance of a class that inherits from BaseAuth for authentication.
        """
        self.auth = auth
        self.obp_base_url = os.getenv("OBP_BASE_URL")
        if not self.obp_base_url:
            raise ValueError("OBP_BASE_URL environment variable is not set.")

    def _extract_username_from_jwt(self, consent_jwt: str) -> str:
        """
        Extract comprehensive user information from JWT token for logging purposes.

        Args:
            consent_jwt (str): The consent JWT token

        Returns:
            str: The primary user identifier for backwards compatibility
        """
        try:
            # Decode JWT without verification (for logging purposes only)
            # Note: This is safe since we're only using it for logging and the JWT
            # is already validated by the OBPConsentAuth.acheck_auth() method
            decoded_token = jwt.decode(consent_jwt, options={"verify_signature": False})

            # Collect all available user information
            user_info = []

            # Human-readable identifiers first
            if decoded_token.get('email'):
                user_info.append(f"email:{decoded_token['email']}")
            if decoded_token.get('name'):
                user_info.append(f"name:{decoded_token['name']}")
            if decoded_token.get('preferred_username'):
                user_info.append(f"preferred_username:{decoded_token['preferred_username']}")
            if decoded_token.get('username'):
                user_info.append(f"username:{decoded_token['username']}")
            if decoded_token.get('user_name'):
                user_info.append(f"user_name:{decoded_token['user_name']}")
            if decoded_token.get('login'):
                user_info.append(f"login:{decoded_token['login']}")

            # System identifiers
            if decoded_token.get('sub'):
                user_info.append(f"sub:{decoded_token['sub']}")
            if decoded_token.get('user_id'):
                user_info.append(f"user_id:{decoded_token['user_id']}")

            # Additional context
            if decoded_token.get('iss'):
                user_info.append(f"iss:{decoded_token['iss']}")
            if decoded_token.get('aud'):
                aud_value = decoded_token['aud']
                if isinstance(aud_value, list):
                    user_info.append(f"aud:{','.join(aud_value)}")
                else:
                    user_info.append(f"aud:{aud_value}")

            user_info_string = ' | '.join(user_info) if user_info else 'unknown'

            logger.info(f"_extract_username_from_jwt says: User consent info - {user_info_string}")

            # Return first (most human) identifier for backwards compatibility
            if user_info:
                return user_info[0].split(':')[1]
            else:
                return 'unknown'

        except jwt.DecodeError as e:
            logger.warning(f"_extract_username_from_jwt says: JWT decode error when extracting user info: {e}")
            return 'unknown'
        except Exception as e:
            logger.warning(f"_extract_username_from_jwt says: Unexpected error extracting user info from JWT: {e}")
            return 'unknown'




    async def _async_request(self, method: str, url: str, body: Any | None):
        try:
            async with aiohttp.ClientSession() as session:
                # construct the headers using the auth object
                headers = self.auth.construct_headers()

                # Log the user information from consent JWT
                consent_jwt = headers.get('Consent-JWT')
                if consent_jwt:
                    userIdentifier = self._extract_username_from_jwt(consent_jwt)
                    logger.info(f"_async_request says: Making OBP API request - Primary user: {userIdentifier}, Method: {method}, URL: {url}")
                else:
                    logger.info(f"_async_request says: Making OBP API request - No consent JWT found (anonymous user), Method: {method}, URL: {url}")

                async with session.request(method, url, json=body, headers=headers) as response:
                    json_response = await response.json()
                    status = response.status
                    logger.info(f"_async_request says: Received response with status {status} from {url}")
                    logger.debug(f"_async_request says: Response content: {json.dumps(json_response, indent=2)}")
                    return json_response, status

        except aiohttp.ClientError as e:
            logger.error(f"_async_request says: Error fetching data from {url}: {e}")
        except asyncio.TimeoutError:
            logger.error(f"_async_request says: Request to {url} timed out")


    async def async_obp_get_requests(self, path: str):
        """
        Exectues a GET request to the OpenBankProject (OBP) API.
        ONLY GET requests are allowed in this mode, but OBP supports all kinds of requests.
        This is a tool that only allows GET requests to be made to the OBP API as a safety measure.
        Args:
            path (str): The API endpoint path to send the request to.
        Returns:
            dict: The JSON response from the OBP API if the request is successful.
            dict: The error response from the OBP API if the request fails.
        Example:
            response = await obp_get_requests('/obp/v4.0.0/banks')
            print(response)
        """
        url = f"{self.obp_base_url}{path}"

        try:
            response = await self._async_request("GET", url, None)
        except Exception as e:
            logger.error(f"async_obp_get_requests says: Error fetching data from {url}: {e}")
            return


        if response is None:
            logger.error("async_obp_get_requests says: OBP returned 'None' response")
            return
        json_response, status = response

        logger.info(f"async_obp_get_requests says: Response from OBP:\n{json.dumps(json_response, indent=2)}")

        # Convert response to JSON string to prevent serialization corruption downstream
        # This fixes the ANK corruption bug by ensuring proper JSON serialization
        try:
            json_string = json.dumps(json_response, ensure_ascii=False, separators=(',', ':'))
            logger.info(f"async_obp_get_requests says: Successfully serialized OBP response to JSON string (length: {len(json_string)})")
        except (TypeError, ValueError) as e:
            logger.error(f"async_obp_get_requests says: JSON serialization error: {e}")
            json_string = json.dumps({"error": "Failed to serialize OBP response", "details": str(json_response)})
            logger.error(f"async_obp_get_requests says: Using fallback error response")

        if status == 200:
            logger.info(f"async_obp_get_requests says: OBP request successful (status: {status})")
            return json_string
        else:
            logger.error(f"async_obp_get_requests says: Error fetching data from OBP (status: {status}): {json_response}")
            # Extract error message from response for better error reporting
            error_msg = "Unknown error"
            if isinstance(json_response, dict):
                error_msg = json_response.get('message', json_response.get('error', json_response.get('failMsg', str(json_response))))
            elif isinstance(json_response, str):
                error_msg = json_response

            raise Exception(f"OBP API error (status: {status}): {error_msg}")



    async def async_obp_requests(self, method: str, path: str, body: str):

        # TODO: Add more descriptive docstring, I think this is required for the llm to know when to call this tool
        """
        Executes a request to the OpenBankProject (OBP) API.
        Args:
            method (str): The HTTP method to use for the request (e.g., 'GET', 'POST').
            path (str): The API endpoint path to send the request to.
            body (str): The JSON body to include in the request. If empty, no body is sent.
        Returns:
            dict: The JSON response from the OBP API if the request is successful.
            dict: The error response from the OBP API if the request fails.
        Raises:
            ValueError: If the response status code is not 200.
        Example:
            response = await obp_requests('GET', '/obp/v4.0.0/banks', '')
            print(response)
        """
        url = f"{self.obp_base_url}{path}"

        if body == '':
            json_body = None
        else:
            json_body = json.loads(body)

        try:
            response = await self._async_request(method, url, json_body)
        except Exception as e:
            logger.error(f"async_obp_requests says: Error fetching data from {url}: {e}")
            return

        if response is None:
            logger.error("async_obp_requests says: OBP returned 'None' response")
            return
        json_response, status = response

        logger.info(f"async_obp_requests says: Response from OBP:\n{json.dumps(json_response, indent=2)}")

        # Convert response to JSON string to prevent serialization corruption downstream
        # This fixes the ANK corruption bug by ensuring proper JSON serialization
        try:
            json_string = json.dumps(json_response, ensure_ascii=False, separators=(',', ':'))
            logger.info(f"async_obp_requests says: Successfully serialized OBP response to JSON string (length: {len(json_string)})")
        except (TypeError, ValueError) as e:
            logger.error(f"async_obp_requests says: JSON serialization error: {e}")
            json_string = json.dumps({"error": "Failed to serialize OBP response", "details": str(json_response)})
            logger.error(f"async_obp_requests says: Using fallback error response")

        if status == 200:
            logger.info(f"async_obp_requests says: OBP request successful (status: {status})")
            return json_string
        else:
            logger.error(f"async_obp_requests says: Error fetching data from OBP (status: {status}): {json_response}")
            # Extract error message from response for better error reporting
            error_msg = "Unknown error"
            if isinstance(json_response, dict):
                error_msg = json_response.get('message', json_response.get('error', json_response.get('failMsg', str(json_response))))
            elif isinstance(json_response, str):
                error_msg = json_response

            raise Exception(f"OBP API error (status: {status}): {error_msg}")


    def get_langchain_tool(self, mode: Literal["safe", "dangerous", "test"]):
        """
        Returns the langchain tool for the OBP requests module.
        Args:
            mode (str): The mode to use for the langchain tool. Can be "safe", "dangerous", or "test".
        Returns:
            StructuredTool: The langchain tool for the OBP requests module.
        """

        match mode:
            case "safe":
                return StructuredTool.from_function(
                    coroutine=self.async_obp_get_requests,
                    name="obp_requests",
                    description=self.async_obp_get_requests.__doc__,
                )
            case "dangerous":
                return StructuredTool.from_function(
                    coroutine=self.async_obp_requests,
                    name="obp_requests",
                    description=self.async_obp_requests.__doc__,
                )
            case "test":
                return StructuredTool.from_function(
                    coroutine=self.async_obp_requests,
                    name="obp_requests",
                    description=self.async_obp_requests.__doc__,
                )
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'safe', 'dangerous', or 'test'.")
