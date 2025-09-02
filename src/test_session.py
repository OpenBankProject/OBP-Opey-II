#!/usr/bin/env python3
"""
Simple test script to debug session creation and cookie handling.
"""

import os
import sys
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_session_creation():
    """Test session creation and cookie handling."""
    
    # Check required environment variables
    print("=== Environment Check ===")
    required_vars = [
        "SESSION_SECRET_KEY",
        "ALLOW_ANONYMOUS_SESSIONS"
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✓ {var}: {'*' * len(value)}")  # Hide actual value
        else:
            print(f"✗ {var}: NOT SET")
    
    print(f"SECURE_COOKIES: {os.getenv('SECURE_COOKIES', 'false')}")
    print(f"PORT: {os.getenv('PORT', '5000')}")
    
    # Test session creation
    print("\n=== Session Creation Test ===")
    base_url = "http://localhost:5000"
    
    try:
        # Create a persistent client that maintains cookies
        with httpx.Client() as client:
            print(f"Attempting to create session at: {base_url}/create-session")
            
            # Call /create-session
            response = client.post(f"{base_url}/create-session")
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            print(f"Cookies received: {response.cookies}")
            
            if response.status_code == 200:
                print("✓ Session created successfully")
                try:
                    data = response.json()
                    print(f"Response data: {data}")
                except:
                    print("Response is not JSON")
            else:
                print(f"✗ Session creation failed: {response.text}")
                return False
            
            # Test if we can make a request to an authenticated endpoint
            print("\n=== Testing Authenticated Endpoint ===")
            
            # Try /status endpoint which requires session
            status_response = client.get(f"{base_url}/status")
            print(f"Status endpoint response: {status_response.status_code}")
            
            if status_response.status_code == 200:
                print("✓ Session is working correctly")
                try:
                    status_data = status_response.json()
                    print(f"Status data: {status_data}")
                except:
                    print("Status response is not JSON")
                return True
            else:
                print(f"✗ Session not working: {status_response.text}")
                print(f"Cookies being sent: {client.cookies}")
                return False
                
    except Exception as e:
        print(f"✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_invoke_endpoint():
    """Test the /invoke endpoint directly."""
    print("\n=== Direct Invoke Endpoint Test ===")
    
    try:
        base_url = "http://localhost:5000"
        
        with httpx.Client() as client:
            # Create session first
            session_response = client.post(f"{base_url}/create-session")
            if session_response.status_code != 200:
                print(f"✗ Session creation failed: {session_response.status_code}")
                return False
            
            # Test /invoke endpoint
            payload = {
                "message": "Hello, this is a test message"
            }
            
            print(f"Sending POST to {base_url}/invoke with payload: {payload}")
            invoke_response = client.post(f"{base_url}/invoke", json=payload)
            
            print(f"Invoke response status: {invoke_response.status_code}")
            print(f"Invoke response headers: {dict(invoke_response.headers)}")
            
            if invoke_response.status_code == 200:
                print("✓ Direct invoke endpoint working")
                try:
                    data = invoke_response.json()
                    print(f"Response data type: {type(data)}")
                    print(f"Response keys: {data.keys() if isinstance(data, dict) else 'Not a dict'}")
                except Exception as json_error:
                    print(f"JSON parsing error: {json_error}")
                    print(f"Raw response: {invoke_response.text}")
                return True
            else:
                print(f"✗ Direct invoke failed: {invoke_response.text}")
                return False
                
    except Exception as e:
        print(f"✗ Direct invoke test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_service_logs():
    """Check if we can get more info from service logs."""
    print("\n=== Service Log Check ===")
    
    try:
        base_url = "http://localhost:5000"
        
        with httpx.Client() as client:
            # Create session first
            session_response = client.post(f"{base_url}/create-session")
            if session_response.status_code != 200:
                print(f"✗ Session creation failed: {session_response.status_code}")
                return False
            
            # Check status endpoint to see if agent is initialized
            status_response = client.get(f"{base_url}/status")
            print(f"Status response: {status_response.status_code}")
            
            if status_response.status_code == 200:
                status_data = status_response.json()
                print(f"Status data: {status_data}")
            elif status_response.status_code == 500:
                print("✗ Status endpoint shows agent not initialized")
                print("This suggests the OpeySession.graph compilation is failing")
                print("Check the service logs for more details about agent initialization")
                return False
            
            return True
                
    except Exception as e:
        print(f"✗ Service log check error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_agent_client():
    """Test the AgentClient session handling."""
    print("\n=== AgentClient Test ===")
    
    try:
        # Import here to avoid import issues if there are problems
        sys.path.append(os.path.dirname(__file__))
        from client import AgentClient
        
        client = AgentClient(base_url="http://localhost:5000")
        
        print("Testing AgentClient.invoke...")
        response = client.invoke("Hello, this is a test message")
        print(f"✓ AgentClient working: {type(response)}")
        return True
        
    except Exception as e:
        print(f"✗ AgentClient failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Session Debug Test")
    print("=" * 50)
    
    # Test basic session creation
    session_ok = test_session_creation()
    
    if session_ok:
        # Check service logs first
        logs_ok = test_service_logs()
        
        if logs_ok:
            # Test direct invoke endpoint
            invoke_ok = test_invoke_endpoint()
            
            if invoke_ok:
                # Test AgentClient if direct invoke works
                agent_ok = test_agent_client()
                
                if agent_ok:
                    print("\n🎉 All tests passed! The client should work now.")
                else:
                    print("\n❌ AgentClient has issues.")
            else:
                print("\n❌ Direct invoke endpoint failed.")
        else:
            print("\n❌ Service has initialization issues.")
            print("\nThe agent graph is not being compiled successfully.")
            print("Check the service startup logs for agent compilation errors.")
    else:
        print("\n❌ Basic session creation failed.")
        print("\nTroubleshooting steps:")
        print("1. Make sure the service is running: python run_service.py")
        print("2. Check that ALLOW_ANONYMOUS_SESSIONS=true in .env")
        print("3. Check that SESSION_SECRET_KEY is set in .env")
        print("4. Make sure SECURE_COOKIES=false for localhost testing")
        print("5. Check service logs for agent initialization errors")
        print("6. Ensure all required API keys are set (OPENAI_API_KEY, etc.)")