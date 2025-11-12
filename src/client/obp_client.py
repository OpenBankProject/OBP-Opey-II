from auth.auth import BaseAuth
import aiohttp
import asyncio
import os
import json
import logging

from typing import Any, Literal, Optional
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


class OBPClient:
    """HTTP client for the Open Bank Project (OBP) API."""
    
    def __init__(self, auth: BaseAuth):
        """
        Initialize the OBPClient with an authentication object.

        Args:
            auth (BaseAuth): An instance of a class that inherits from BaseAuth for authentication.
        """
        self.auth = auth
        self.obp_base_url = os.getenv("OBP_BASE_URL")
        if not self.obp_base_url:
            raise ValueError("OBP_BASE_URL environment variable is not set.")

    def _extract_username_from_jwt(self, consent_id: str) -> str:
        # need to create a function that extracts the username from the consent ID
        pass

    async def _async_request(self, method: str, url: str, body: Any | None):
        try:
            async with aiohttp.ClientSession() as session:
                headers = self.auth.construct_headers()

                # Log the user information from consent JWT
                consent_id = headers.get('Consent-Id')
                if consent_id:
                    logger.info(f"_async_request says: Making OBP API request - Primary user consentID: {consent_id}, Method: {method}, URL: {url}")
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

    async def async_obp_get_requests(self, path: str, operation_id: str | None = None):
        """
        Exectues a GET request to the OpenBankProject (OBP) API.
        ONLY GET requests are allowed in this mode, but OBP supports all kinds of requests.
        This is a tool that only allows GET requests to be made to the OBP API as a safety measure.
        Args:
            path (str): The API endpoint path to send the request to.
            operation_id (str, optional): The OBP API operation ID for this endpoint (used for approval tracking).
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

    async def async_obp_requests(self, method: str, path: str, body: str, operation_id: str | None = None):
        """
        Executes a request to the OpenBankProject (OBP) API.
        Args:
            method (str): The HTTP method to use for the request (e.g., 'GET', 'POST').
            path (str): The API endpoint path to send the request to.
            body (str): The JSON body to include in the request. If empty, no body is sent.
            operation_id (str, optional): The OBP API operation ID for this endpoint (used for approval tracking). Use the same operationId as in the docs.
        Returns:
            dict: The JSON response from the OBP API if the request is successful.
            dict: The error response from the OBP API if the request fails.
        Raises:
            ValueError: If the response status code is not in the 2xx range.
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

        if 200 <= status < 300:  # Accept all 2xx status codes as success
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

    def sync_obp_requests(self, method: str, path: str, body: str, as_json: bool = False):
        """
        Synchronous wrapper for async_obp_requests.
        Mainly for use in admin scripts and non-async contexts.
        I.e. don't use this with the langchain tools or agent.
        
        Args:
            method (str): The HTTP method to use for the request (e.g., 'GET', 'POST').
            path (str): The API endpoint path to send the request to.
            body (str): The JSON body to include in the request. If empty, no body is sent.
        """
        try:
            response = asyncio.run(self.async_obp_requests(method, path, body))
            
        except Exception as e:
            logger.error(f"Error fetching data from {path}: {e}")
            raise
        
        if as_json and response is not None:
            return json.loads(response)
        
        
        return response