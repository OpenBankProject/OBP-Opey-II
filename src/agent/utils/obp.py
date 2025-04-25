from auth.auth import BaseAuth
import aiohttp
import asyncio
import os
import json

from typing import Any, Literal
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
                return NotImplementedError("Test mode is not implemented yet.")
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'safe', 'dangerous', or 'test'.")