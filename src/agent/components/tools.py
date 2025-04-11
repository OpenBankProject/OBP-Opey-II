import json
import requests
import aiohttp
import asyncio

from langchain_core.tools import tool

from typing import Any

from agent.utils.config import obp_base_url, auth
from agent.components.sub_graphs.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.sub_graphs.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph


async def _async_request(method: str, url: str, body: Any | None, headers: dict[str, str] | None = None):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=body, headers=headers) as response:
                json_response = await response.json()
                status = response.status
                return json_response, status
            
    except aiohttp.ClientError as e:
        print(f"Error fetching data from {url}: {e}")
    except asyncio.TimeoutError:
        print(f"Request to {url} timed out")

@tool
async def obp_requests(method: str, path: str, body: str):
    
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
    url = f"{obp_base_url}{path}"
    headers = auth.construct_headers()
    
    if body == '':
        json_body = None
    else:
        json_body = json.loads(body)
        
    try:
        response = await _async_request(method, url, json_body, headers=headers)
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
    
    

# Define endpoint retrieval tool nodes

endpoint_retrieval_tool = endpoint_retrieval_graph.as_tool(name="retrieve_endpoints")
glossary_retrieval_tool = glossary_retrieval_graph.as_tool(name="retrieve_glossary")