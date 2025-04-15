from auth.auth import BaseAuth
import aiohttp
import asyncio
import os
import json

from typing import Any
from langchain_core.tools import StructuredTool


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
        
        self.langchain_tool = StructuredTool.from_function(
            coroutine=self.async_obp_requests,
            name="obp_requests",
            description="Executes a request to the OpenBankProject (OBP) API. "
                        "Args: method (str): The HTTP method to use for the request (e.g., 'GET', 'POST'). "
                        "path (str): The API endpoint path to send the request to. "
                        "body (str): The JSON body to include in the request. If empty, no body is sent. "
                        "Returns: dict: The JSON response from the OBP API if the request is successful. "
                        "dict: The error response from the OBP API if the request fails.",
        )


    async def _async_request(self, method: str, url: str, body: Any | None):
        try:
            async with aiohttp.ClientSession() as session:
                # construct the headers using the auth object
                headers = self.auth.construct_headers()
                async with session.request(method, url, json=body, headers=headers) as response:
                    json_response = await response.json()
                    status = response.status
                    return json_response, status
                
        except aiohttp.ClientError as e:
            print(f"Error fetching data from {url}: {e}")
        except asyncio.TimeoutError:
            print(f"Request to {url} timed out")


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
            print(f"Error fetching data from {url}: {e}")
            return
        
        if response is None:
            print("OBP returned 'None' response")
            return
        json_response, status = response

        print("Response from OBP:\n", json.dumps(json_response, indent=2))
        
        if status == 200:
            return json_response
        else:
            print("Error fetching data from OBP:", json_response)
            return json_response
    