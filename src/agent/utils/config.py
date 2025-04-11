import os
import requests
from dotenv import load_dotenv
from auth import OBPConsentAuth, OBPDirectLoginAuth

load_dotenv()

obp_base_url = os.getenv("OBP_BASE_URL")
username = os.getenv("OBP_USERNAME")
password = os.getenv("OBP_PASSWORD")
consumer_key = os.getenv("OBP_CONSUMER_KEY")

def get_direct_login_token():
    url = f"{obp_base_url}/my/logins/direct"
    headers = {
        "Content-Type": "application/json",
        "directlogin": f"username={username},password={password},consumer_key={consumer_key}"
    }
    
    response = requests.post(url, headers=headers)
    if response.status_code == 201:
        token = response.json().get('token')
        print("Token fetched successfully!")
        return token
    else:
        print("Error fetching token:", response.json())
        return None

if os.getenv("USE_OBP_CONSENTS") == "true":
    auth = OBPConsentAuth()
else:
    auth = OBPDirectLoginAuth(config={
        "username": username,
        "password": password,
        "consumer_key": consumer_key,
        "base_uri": obp_base_url
    })
    

def get_headers():
    token = get_direct_login_token()
    if token:
        return {
            "Authorization": f"DirectLogin token={token}",
            "Content-Type": "application/json"
        }
    else:
        return None