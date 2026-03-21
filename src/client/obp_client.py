from auth.auth import BaseAuth
import aiohttp
import asyncio
import json
import logging
import os

from typing import Literal
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


class OBPResponse:
    """Response object mimicking requests.Response interface for OBP API calls."""
    
    def __init__(self, data: dict | list, status_code: int, url: str, headers: dict):
        self._json_data = data
        self.status_code = status_code
        self.url = url
        self.headers = headers
        self.ok = 200 <= status_code < 300
    
    def json(self) -> dict | list:
        """Return the JSON-decoded content of the response."""
        return self._json_data
    
    @property
    def text(self) -> str:
        """Return the response content as a string."""
        return json.dumps(self._json_data, ensure_ascii=False, separators=(',', ':'))
    
    def raise_for_status(self):
        """Raise an exception if the response status is not OK."""
        if not self.ok:
            error_msg = "Unknown error"
            if isinstance(self._json_data, dict):
                error_msg = self._json_data.get('message', 
                                                 self._json_data.get('error', 
                                                                     self._json_data.get('failMsg', str(self._json_data))))
            raise Exception(f"HTTP {self.status_code}: {error_msg}")
    
    def __repr__(self) -> str:
        return f"<OBPResponse [{self.status_code}]>"


class OBPClient:
    """HTTP client for the Open Bank Project (OBP) API using aiohttp."""
    
    def __init__(self, auth: BaseAuth):
        """
        Initialize the OBPClient with an authentication object.

        Args:
            auth: An instance of a class that inherits from BaseAuth for authentication.
        """
        self.auth = auth
        self.obp_base_url = os.getenv("OBP_BASE_URL")
        if not self.obp_base_url:
            raise ValueError("OBP_BASE_URL environment variable is not set.")
        self._session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        return False

    async def _make_request(self, method: str, path: str, body: dict | None = None, operation_id: str | None = None) -> OBPResponse:
        """
        Make an async HTTP request to the OBP API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: The API endpoint path.
            body: Optional JSON body for the request.
            operation_id: Optional OBP API operation ID for approval tracking.
            
        Returns:
            OBPResponse object with requests.Response-like interface.
        """
        url = f"{self.obp_base_url}{path}"
        headers = self.auth.construct_headers()
        
        # Log the user information from consent JWT
        consent_id = headers.get('Consent-Id')
        if consent_id:
            logger.info(f"OBP {method} request - Consent ID: {consent_id}, URL: {url}")
        else:
            logger.info(f"OBP {method} request - No consent JWT (anonymous), URL: {url}")
        
        session = await self._get_session()
        
        try:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response_data = await response.json()
                status = response.status
                response_headers = dict(response.headers)
                
                logger.info(f"OBP {method} request: Response status {status} from {url}")
                
                obp_response = OBPResponse(
                    data=response_data,
                    status_code=status,
                    url=url,
                    headers=response_headers
                )
                
                if obp_response.ok:
                    logger.debug(f"OBP {method} response: {obp_response.text[:500]}")
                else:
                    logger.error(f"OBP {method} error ({status}): {obp_response.text[:500]}")
                
                return obp_response
                    
        except aiohttp.ClientError as e:
            logger.error(f"OBP {method} request failed for {url}: {e}")
            raise
        except asyncio.TimeoutError as e:
            logger.error(f"OBP {method} request timed out for {url}: {e}")
            raise

    async def get(self, path: str, operation_id: str | None = None) -> OBPResponse:
        """
        Execute a GET request to the OBP API.
        
        Args:
            path: The API endpoint path.
            operation_id: The OBP API operation ID for approval tracking.
            
        Returns:
            OBPResponse object.
            
        Example:
            response = await client.get('/obp/v4.0.0/banks')
            data = response.json()
        """
        return await self._make_request("GET", path, operation_id=operation_id)

    async def post(self, path: str, body: dict | None = None, operation_id: str | None = None) -> OBPResponse:
        """
        Execute a POST request to the OBP API.
        
        Args:
            path: The API endpoint path.
            body: The JSON body to include in the request.
            operation_id: The OBP API operation ID for approval tracking.
            
        Returns:
            OBPResponse object.
            
        Example:
            response = await client.post('/obp/v4.0.0/banks/BANK_ID/accounts', body={'name': 'test'})
            data = response.json()
        """
        return await self._make_request("POST", path, body=body, operation_id=operation_id)

    async def put(self, path: str, body: dict | None = None, operation_id: str | None = None) -> OBPResponse:
        """
        Execute a PUT request to the OBP API.
        
        Args:
            path: The API endpoint path.
            body: The JSON body to include in the request.
            operation_id: The OBP API operation ID for approval tracking.
            
        Returns:
            OBPResponse object.
            
        Example:
            response = await client.put('/obp/v4.0.0/banks/BANK_ID/accounts/ACCOUNT_ID', body={'name': 'updated'})
            data = response.json()
        """
        return await self._make_request("PUT", path, body=body, operation_id=operation_id)

    async def delete(self, path: str, operation_id: str | None = None) -> OBPResponse:
        """
        Execute a DELETE request to the OBP API.
        
        Args:
            path: The API endpoint path.
            operation_id: The OBP API operation ID for approval tracking.
            
        Returns:
            OBPResponse object.
            
        Example:
            response = await client.delete('/obp/v4.0.0/banks/BANK_ID/accounts/ACCOUNT_ID')
            data = response.json()
        """
        return await self._make_request("DELETE", path, operation_id=operation_id)

    async def patch(self, path: str, body: dict | None = None, operation_id: str | None = None) -> OBPResponse:
        """
        Execute a PATCH request to the OBP API.
        
        Args:
            path: The API endpoint path.
            body: The JSON body to include in the request.
            operation_id: The OBP API operation ID for approval tracking.
            
        Returns:
            OBPResponse object.
            
        Example:
            response = await client.patch('/obp/v4.0.0/banks/BANK_ID/accounts/ACCOUNT_ID', body={'status': 'active'})
            data = response.json()
        """
        return await self._make_request("PATCH", path, body=body, operation_id=operation_id)

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
                    
                    response: OBPResponse
                    match method:
                        case "GET":
                            response = await self.get(path, operation_id)
                        case "POST":
                            response = await self.post(path, json_body, operation_id)
                        case "PUT":
                            response = await self.put(path, json_body, operation_id)
                        case "DELETE":
                            response = await self.delete(path, operation_id)
                        case "PATCH":
                            response = await self.patch(path, json_body, operation_id)
                        case _:
                            raise ValueError(f"Unsupported HTTP method: {method}")
                    
                    # Return JSON string for LangChain tool compatibility
                    return response.text
                
                return StructuredTool.from_function(
                    coroutine=obp_requests,
                    name="obp_requests",
                    description=obp_requests.__doc__,
                )
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'safe', 'dangerous', or 'test'.")

