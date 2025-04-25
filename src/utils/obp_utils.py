import json
import requests
import aiohttp
import asyncio
import os

from typing import Any

from dotenv import load_dotenv

load_dotenv()
# Config load from .env file

obp_base_url = os.getenv("OBP_BASE_URL")
username = os.getenv("OBP_USERNAME")
password = os.getenv("OBP_PASSWORD")
consumer_key = os.getenv("OBP_CONSUMER_KEY")

def get_direct_login_token(obp_base_url: str = obp_base_url, username: str = username, password: str = password, consumer_key: str = consumer_key):
    url = f"{obp_base_url}/my/logins/direct"
    headers = {
        "Content-Type": "application/json",
        "directlogin": f"username={username},password={password},consumer_key={consumer_key}"
    }
    
    print("Headers:", headers)

    response = requests.post(url, headers=headers)
    if response.status_code == 201:
        token = response.json().get('token')
        print("Token fetched successfully!")
        return token
    else:
        print("Error fetching token:", response.json())
        return None


async def _async_request(method: str, url: str, body: Any | None, headers: dict[str, str] | None = None):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=body, headers=headers) as response:
                json_response = await response.json()
                return response, json_response
            
    except aiohttp.ClientError as e:
        print(f"Error fetching data from {url}: {e}")
    except asyncio.TimeoutError:
        print(f"Request to {url} timed out")

def get_headers(**kwargs):
    token = get_direct_login_token(**kwargs)
    if token:
        return {
            "Authorization": f"DirectLogin token={token}",
            "Content-Type": "application/json"
        }
    else:
        return None

def sync_obp_requests(method: str, path: str, body: str, **kwargs):
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
        response = obp_requests('GET', '/obp/v4.0.0/banks', '')
        print(response)
    """
    url = f"{obp_base_url}{path}"
    headers = get_headers(**kwargs)
    
    if body == '':
        json_body = None
    else:
        json_body = json.loads(body)
        
    try:
        r = requests.request(method, url, data=json.dumps(json_body), headers=headers)
    except Exception as e:
        print(f"Error fetching data from {url}: {e}")
        return
    
    
    if r == None:
        raise ValueError("No response received from OBP")
     

    print("Response from OBP:\n", r.status_code, r.json())
    
    return r

async def async_obp_requests(method: str, path: str, body: str, **kwargs):
    
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
    headers = get_headers(**kwargs)
    
    if body == '':
        json_body = None
    else:
        json_body = json.loads(body)
        
    try:
        r = await _async_request(method, url, json_body, headers=headers)
    except Exception as e:
        print(f"Error fetching data from {url}: {e}")
        return
    
    
    if r == None:
        raise ValueError("No response received from OBP")

    response, json_response = r 
     

    print("Response from OBP:\n", response.status, json_response)
    
    return response
    
    