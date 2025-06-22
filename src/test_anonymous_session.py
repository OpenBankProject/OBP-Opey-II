import asyncio
import httpx
import json
from client import AgentClient

async def test_anonymous_session():
    """Test anonymous session creation and usage tracking"""

    base_url = "http://localhost:5000"

    async with httpx.AsyncClient() as client:
        print("=== Testing Anonymous Session Creation ===")

        # Test 1: Create anonymous session (no Consent-JWT header)
        response = await client.post(f"{base_url}/create-session")
        print(f"Anonymous session creation status: {response.status_code}")

        # Handle different response types
        try:
            response_data = response.json()
            print(f"Response: {response_data}")
        except Exception as e:
            print(f"Response (text): {response.text}")
            print(f"JSON parse error: {e}")
            if response.status_code == 401:
                print("❌ Anonymous sessions are likely disabled (ALLOW_ANONYMOUS_SESSIONS=false)")
                return
            response_data = {"error": "Invalid response format"}

        # Extract session cookie for subsequent requests
        session_cookie = None
        for cookie in response.cookies:
            if cookie.name == "session":
                session_cookie = f"{cookie.name}={cookie.value}"
                break

        if not session_cookie:
            print("❌ No session cookie found!")
            if response.status_code != 200:
                print(f"❌ Session creation failed with status {response.status_code}")
            return

        print(f"✅ Session cookie: {session_cookie}")

        # Test 2: Check status with usage info
        print("\n=== Testing Status Endpoint ===")
        headers = {"Cookie": session_cookie}
        try:
            response = await client.get(f"{base_url}/status", headers=headers)
            if response.status_code == 200:
                print(f"Status response: {response.json()}")
            else:
                print(f"❌ Status check failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Status check error: {e}")

        # Test 3: Check detailed usage info
        print("\n=== Testing Usage Endpoint ===")
        try:
            response = await client.get(f"{base_url}/usage", headers=headers)
            if response.status_code == 200:
                print(f"Usage response: {response.json()}")
            else:
                print(f"❌ Usage check failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Usage check error: {e}")

        # Test 4: Make some requests to consume tokens/requests
        print("\n=== Testing Request Consumption ===")
        for i in range(3):
            print(f"\nRequest {i+1}:")
            try:
                response = await client.post(
                    f"{base_url}/invoke",
                    json={
                        "message": f"Hello, this is test message {i+1}. Tell me about OBP APIs.",
                        "thread_id": "test-thread-123"
                    },
                    headers=headers
                )
                if response.status_code == 200:
                    result = response.json()
                    print(f"✅ Response received: {result['content'][:100]}...")
                elif response.status_code == 429:
                    print(f"❌ Rate limited: {response.json()}")
                    break
                else:
                    print(f"❌ Error {response.status_code}: {response.text}")
            except Exception as e:
                print(f"❌ Request failed: {e}")

        # Test 5: Check usage after requests
        print("\n=== Testing Usage After Requests ===")
        try:
            response = await client.get(f"{base_url}/usage", headers=headers)
            if response.status_code == 200:
                usage_info = response.json()
                print(f"Updated usage: {usage_info}")
            else:
                print(f"❌ Usage check failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Usage check error: {e}")

        # Test 6: Test session upgrade (requires valid Consent-JWT)
        print("\n=== Testing Session Upgrade ===")
        print("Note: This would require a valid Consent-JWT header to work")
        try:
            response = await client.post(
                f"{base_url}/upgrade-session",
                headers={
                    **headers,
                    "Consent-JWT": "fake-jwt-token"  # This will fail, but shows the flow
                }
            )
            print(f"Upgrade response: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Expected failure for upgrade without valid JWT: {e}")


async def test_authenticated_session():
    """Test authenticated session creation"""

    base_url = "http://localhost:5000"

    async with httpx.AsyncClient() as client:
        print("\n=== Testing Authenticated Session Creation ===")

        # This will fail without a valid Consent-JWT, but shows the flow
        try:
            response = await client.post(
                f"{base_url}/create-session",
                headers={"Consent-JWT": "fake-jwt-token"}
            )
            print(f"Authenticated session status: {response.status_code}")
            if response.status_code == 401:
                print("✅ Correctly rejected invalid JWT")
            else:
                try:
                    print(f"Response: {response.json()}")
                except:
                    print(f"Response: {response.text}")
        except Exception as e:
            print(f"Request error: {e}")


async def test_anonymous_disabled():
    """Test behavior when anonymous sessions are disabled"""
    print("\n=== Testing Anonymous Sessions Disabled ===")
    print("Note: Set ALLOW_ANONYMOUS_SESSIONS=false in .env to test this")

    base_url = "http://localhost:5000"

    async with httpx.AsyncClient() as client:
        # This should fail if anonymous sessions are disabled
        try:
            response = await client.post(f"{base_url}/create-session")
            print(f"Status when anonymous disabled: {response.status_code}")
            if response.status_code == 401:
                print("✅ Correctly rejected anonymous session")
                try:
                    error_detail = response.json()
                    print(f"Error detail: {error_detail}")
                except:
                    print(f"Error text: {response.text}")
            else:
                print("ℹ️ Anonymous sessions are enabled")
                try:
                    print(f"Response: {response.json()}")
                except:
                    print(f"Response: {response.text}")
        except Exception as e:
            print(f"Request error: {e}")


def test_usage_tracker():
    """Test the usage tracker functionality"""
    print("\n=== Testing Usage Tracker ===")

    from auth.usage_tracker import UsageTracker
    from auth.session import SessionData

    tracker = UsageTracker()

    # Test anonymous session data
    session_data = SessionData(
        consent_jwt=None,
        is_anonymous=True,
        token_usage=0,
        request_count=0
    )

    print("Initial usage info:")
    print(json.dumps(tracker.get_usage_info(session_data), indent=2))

    # Update usage
    tracker.update_token_usage(session_data, 100)
    tracker.update_request_count(session_data)

    print("\nAfter updates:")
    print(json.dumps(tracker.get_usage_info(session_data), indent=2))

    # Test limit checking
    session_data.token_usage = 9900  # Near limit
    session_data.request_count = 19   # Near limit

    print("\nNear limits:")
    print(json.dumps(tracker.get_usage_info(session_data), indent=2))

    try:
        tracker.check_anonymous_limits(session_data)
        print("✅ Within limits")
    except Exception as e:
        print(f"❌ Limit exceeded: {e}")


async def main():
    """Run all tests"""
    print("🚀 Starting Anonymous Session Tests")
    print("Make sure the service is running on localhost:5000")
    print("And set ALLOW_ANONYMOUS_SESSIONS=true in your .env file")
    print("=" * 60)

    try:
        # Test local usage tracker
        test_usage_tracker()

        # Test API endpoints
        await test_anonymous_session()
        await test_authenticated_session()
        await test_anonymous_disabled()

        print("\n✅ All tests completed!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
