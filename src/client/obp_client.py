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

    async def _handle_response(self, response: tuple[Any, int] | None, method: str, url: str) -> str:
        """Process and validate OBP API response."""
        if response is None:
            logger.error(f"OBP {method} request: Received 'None' response from {url}")
            raise Exception(f"OBP API returned None response for {method} {url}")
            
        json_response, status = response
        logger.info(f"OBP {method} request: Response from {url}:\n{json.dumps(json_response, indent=2)}")

        # Convert response to JSON string to prevent serialization corruption downstream
        try:
            json_string = json.dumps(json_response, ensure_ascii=False, separators=(',', ':'))
            logger.info(f"OBP {method} request: Successfully serialized response (length: {len(json_string)})")
        except (TypeError, ValueError) as e:
            logger.error(f"OBP {method} request: JSON serialization error: {e}")
            json_string = json.dumps({"error": "Failed to serialize OBP response", "details": str(json_response)})
            logger.error(f"OBP {method} request: Using fallback error response")

        if 200 <= status < 300:
            logger.info(f"OBP {method} request: Successful (status: {status})")
            return json_string
        else:
            logger.error(f"OBP {method} request: Error (status: {status}): {json_response}")
            error_msg = "Unknown error"
            if isinstance(json_response, dict):
                error_msg = json_response.get('message', json_response.get('error', json_response.get('failMsg', str(json_response))))
            elif isinstance(json_response, str):
                error_msg = json_response
            raise Exception(f"OBP API error (status: {status}): {error_msg}")

    async def get(self, path: str, operation_id: str | None = None) -> str:
        """
        Execute a GET request to the OBP API.
        
        Args:
            path: The API endpoint path to send the request to.
            operation_id: The OBP API operation ID for this endpoint (used for approval tracking).
            
        Returns:
            JSON string response from the OBP API.
            
        Example:
            response = await client.get('/obp/v4.0.0/banks')
        """
        url = f"{self.obp_base_url}{path}"
        try:
            response = await self._async_request("GET", url, None)
            return await self._handle_response(response, "GET", url)
        except Exception as e:
            logger.error(f"GET request error for {url}: {e}")
            raise

    async def post(self, path: str, body: dict | None = None, operation_id: str | None = None) -> str:
        """
        Execute a POST request to the OBP API.
        
        Args:
            path: The API endpoint path to send the request to.
            body: The JSON body to include in the request.
            operation_id: The OBP API operation ID for this endpoint (used for approval tracking).
            
        Returns:
            JSON string response from the OBP API.
            
        Example:
            response = await client.post('/obp/v4.0.0/banks/BANK_ID/accounts', body={'name': 'test'})
        """
        url = f"{self.obp_base_url}{path}"
        try:
            response = await self._async_request("POST", url, body)
            return await self._handle_response(response, "POST", url)
        except Exception as e:
            logger.error(f"POST request error for {url}: {e}")
            raise

    async def put(self, path: str, body: dict | None = None, operation_id: str | None = None) -> str:
        """
        Execute a PUT request to the OBP API.
        
        Args:
            path: The API endpoint path to send the request to.
            body: The JSON body to include in the request.
            operation_id: The OBP API operation ID for this endpoint (used for approval tracking).
            
        Returns:
            JSON string response from the OBP API.
            
        Example:
            response = await client.put('/obp/v4.0.0/banks/BANK_ID/accounts/ACCOUNT_ID', body={'name': 'updated'})
        """
        url = f"{self.obp_base_url}{path}"
        try:
            response = await self._async_request("PUT", url, body)
            return await self._handle_response(response, "PUT", url)
        except Exception as e:
            logger.error(f"PUT request error for {url}: {e}")
            raise

    async def delete(self, path: str, operation_id: str | None = None) -> str:
        """
        Execute a DELETE request to the OBP API.
        
        Args:
            path: The API endpoint path to send the request to.
            operation_id: The OBP API operation ID for this endpoint (used for approval tracking).
            
        Returns:
            JSON string response from the OBP API.
            
        Example:
            response = await client.delete('/obp/v4.0.0/banks/BANK_ID/accounts/ACCOUNT_ID')
        """
        url = f"{self.obp_base_url}{path}"
        try:
            response = await self._async_request("DELETE", url, None)
            return await self._handle_response(response, "DELETE", url)
        except Exception as e:
            logger.error(f"DELETE request error for {url}: {e}")
            raise

    async def patch(self, path: str, body: dict | None = None, operation_id: str | None = None) -> str:
        """
        Execute a PATCH request to the OBP API.
        
        Args:
            path: The API endpoint path to send the request to.
            body: The JSON body to include in the request.
            operation_id: The OBP API operation ID for this endpoint (used for approval tracking).
            
        Returns:
            JSON string response from the OBP API.
            
        Example:
            response = await client.patch('/obp/v4.0.0/banks/BANK_ID/accounts/ACCOUNT_ID', body={'status': 'active'})
        """
        url = f"{self.obp_base_url}{path}"
        try:
            response = await self._async_request("PATCH", url, body)
            return await self._handle_response(response, "PATCH", url)
        except Exception as e:
            logger.error(f"PATCH request error for {url}: {e}")
            raise

    def get_langchain_tool(self, mode: Literal["safe", "dangerous", "test"]):
        """
        Returns the langchain tool for the OBP requests module.
        
        Args:
            mode: The mode to use for the langchain tool. Can be "safe", "dangerous", or "test".
            
        Returns:
            StructuredTool: The langchain tool for the OBP requests module.
        """
        match mode:
            case "safe":
                return StructuredTool.from_function(
                    coroutine=self.get,
                    name="obp_requests",
                    description=self.get.__doc__,
                )
            case "dangerous" | "test":
                async def obp_requests(method: str, path: str, body: str = "", operation_id: str | None = None) -> str:
                    """
                    Make HTTP requests to the OBP API.
                    
                    Args:
                        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
                        path: The API endpoint path.
                        body: JSON body as string (use empty string for GET/DELETE).
                        operation_id: The OBP API operation ID (used for approval tracking).
                        
                    Returns:
                        JSON string response from the OBP API.
                    """
                    method = method.upper()
                    json_body = json.loads(body) if body else None
                    
                    match method:
                        case "GET":
                            return await self.get(path, operation_id)
                        case "POST":
                            return await self.post(path, json_body, operation_id)
                        case "PUT":
                            return await self.put(path, json_body, operation_id)
                        case "DELETE":
                            return await self.delete(path, operation_id)
                        case "PATCH":
                            return await self.patch(path, json_body, operation_id)
                        case _:
                            raise ValueError(f"Unsupported HTTP method: {method}")
                
                return StructuredTool.from_function(
                    coroutine=obp_requests,
                    name="obp_requests",
                    description=obp_requests.__doc__,
                )
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'safe', 'dangerous', or 'test'.")

    def sync_get(self, path: str, as_json: bool = False) -> str | dict:
        """
        Synchronous GET request wrapper.
        
        Args:
            path: The API endpoint path.
            as_json: If True, return parsed JSON dict instead of string.
            
        Returns:
            JSON string or dict response from the OBP API.
        """
        try:
            response = asyncio.run(self.get(path))
        except Exception as e:
            logger.error(f"Sync GET request error for {path}: {e}")
            raise
        
        if as_json and response is not None:
            return json.loads(response)
        return response

    def sync_post(self, path: str, body: dict | None = None, as_json: bool = False) -> str | dict:
        """
        Synchronous POST request wrapper.
        
        Args:
            path: The API endpoint path.
            body: The JSON body to include in the request.
            as_json: If True, return parsed JSON dict instead of string.
            
        Returns:
            JSON string or dict response from the OBP API.
        """
        try:
            response = asyncio.run(self.post(path, body))
        except Exception as e:
            logger.error(f"Sync POST request error for {path}: {e}")
            raise
        
        if as_json and response is not None:
            return json.loads(response)
        return response

    def sync_put(self, path: str, body: dict | None = None, as_json: bool = False) -> str | dict:
        """
        Synchronous PUT request wrapper.
        
        Args:
            path: The API endpoint path.
            body: The JSON body to include in the request.
            as_json: If True, return parsed JSON dict instead of string.
            
        Returns:
            JSON string or dict response from the OBP API.
        """
        try:
            response = asyncio.run(self.put(path, body))
        except Exception as e:
            logger.error(f"Sync PUT request error for {path}: {e}")
            raise
        
        if as_json and response is not None:
            return json.loads(response)
        return response

    def sync_delete(self, path: str, as_json: bool = False) -> str | dict:
        """
        Synchronous DELETE request wrapper.
        
        Args:
            path: The API endpoint path.
            as_json: If True, return parsed JSON dict instead of string.
            
        Returns:
            JSON string or dict response from the OBP API.
        """
        try:
            response = asyncio.run(self.delete(path))
        except Exception as e:
            logger.error(f"Sync DELETE request error for {path}: {e}")
            raise
        
        if as_json and response is not None:
            return json.loads(response)
        return response