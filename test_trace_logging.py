#!/usr/bin/env python3
"""
Test script to demonstrate trace-level logging for OBP consent operations.
This script shows the detailed logging that occurs when OBP consent is processed.
"""

import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

# Add src directory to path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from auth.auth import OBPConsentAuth
from agent.utils.obp import OBPRequestsModule

load_dotenv()

# Configure logging to DEBUG level to see TRACE messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

async def test_consent_trace_logging():
    """
    Test trace logging for OBP consent operations.
    This will demonstrate all the trace logs we've added.
    """
    print("=" * 80)
    print("TRACE LOGGING TEST FOR OBP CONSENT")
    print("=" * 80)

    # Example JWT token (this is just for demo - would normally come from frontend)
    # In real usage, this would be a valid JWT from the OBP consent process
    sample_jwt = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3Qub3BlbmJhbmtwcm9qZWN0LmNvbSIsInN1YiI6IjEyMzQ1Njc4OTAiLCJuYW1lIjoiSm9obiBEb2UiLCJlbWFpbCI6ImpvaG4uZG9lQGV4YW1wbGUuY29tIiwiaWF0IjoxNTE2MjM5MDIyLCJleHAiOjk5OTk5OTk5OTksImF1ZCI6WyJ0ZXN0LWF1ZGllbmNlIl0sInVzZXJuYW1lIjoidGVzdC11c2VyIiwicHJlZmVycmVkX3VzZXJuYW1lIjoidGVzdC11c2VyIn0.invalid_signature_for_demo"

    print("\n1. Testing OBP Consent Auth Creation and Header Construction")
    print("-" * 60)

    try:
        # Create OBP consent auth with the sample JWT
        consent_auth = OBPConsentAuth(consent_jwt=sample_jwt)
        print("✓ OBPConsentAuth created successfully")

        # Test header construction (this will show TRACE logs)
        headers = consent_auth.construct_headers()
        print("✓ Headers constructed successfully")

    except Exception as e:
        print(f"✗ Error creating consent auth or constructing headers: {e}")
        return False

    print("\n2. Testing JWT User Information Extraction")
    print("-" * 60)

    try:
        # Create OBP requests module
        obp_module = OBPRequestsModule(auth=consent_auth)
        print("✓ OBPRequestsModule created successfully")

        # Test JWT extraction (this will show detailed TRACE logs)
        user_identifier = obp_module._extract_username_from_jwt(sample_jwt)
        print(f"✓ User identifier extracted: {user_identifier}")

    except Exception as e:
        print(f"✗ Error extracting user info from JWT: {e}")
        return False

    print("\n3. Testing OBP API Request Preparation (Headers Only)")
    print("-" * 60)

    try:
        # This will show the TRACE logs for request preparation without actually making the request
        # We'll just prepare the request to see the logging
        print("Note: This would normally make an actual OBP API request, but we're just showing the debug logging preparation.")
        print("The DEBUG logs above show:")
        print("  - JWT payload analysis")
        print("  - Header construction details")
        print("  - User identification extraction")
        print("  - Masked JWT tokens for security")

    except Exception as e:
        print(f"✗ Error in request preparation: {e}")
        return False

    print("\n4. Environment Configuration Check")
    print("-" * 60)

    # Check environment variables
    obp_base_url = os.getenv('OBP_BASE_URL')
    consumer_key = os.getenv('OBP_CONSUMER_KEY')
    opey_consumer_key = os.getenv('OPEY_CONSUMER_KEY')
    log_level = os.getenv('LOG_LEVEL', 'INFO')

    print(f"OBP_BASE_URL: {'✓ Set' if obp_base_url else '✗ Not set'}")
    print(f"OBP_CONSUMER_KEY: {'✓ Set' if consumer_key else '✗ Not set'}")
    print(f"OPEY_CONSUMER_KEY: {'✓ Set' if opey_consumer_key else '✗ Not set'}")
    print(f"LOG_LEVEL: {log_level}")

    if log_level.upper() != 'DEBUG':
        print("\n⚠️  WARNING: LOG_LEVEL is not set to DEBUG")
        print("   Set LOG_LEVEL=DEBUG in your environment to see all DEBUG messages")
    else:
        print("\n✓ LOG_LEVEL is set to DEBUG - all DEBUG messages should be visible")

    print("\n" + "=" * 80)
    print("TRACE LOGGING TEST COMPLETED")
    print("=" * 80)
    print("\nWhat you should see in the logs above:")
    print("• DEBUG: JWT payload keys and detailed analysis")
    print("• DEBUG: JWT expiry information")
    print("• DEBUG: Header construction with masked JWT tokens")
    print("• DEBUG: Consumer key information")
    print("• User consent info extraction with all available fields")
    print("\nThese logs will appear when making actual OBP API requests in production.")

    return True

def test_without_jwt():
    """Test what happens when no JWT is provided."""
    print("\n" + "=" * 80)
    print("TESTING WITHOUT JWT (Anonymous Mode)")
    print("=" * 80)

    try:
        # Try to create consent auth without JWT
        consent_auth = OBPConsentAuth()
        print("✓ OBPConsentAuth created without JWT")

        # This should fail when trying to construct headers
        try:
            headers = consent_auth.construct_headers()
            print("✗ Unexpected success - should have failed without JWT")
        except ValueError as e:
            print(f"✓ Expected error when no JWT provided: {e}")

    except Exception as e:
        print(f"Error in anonymous test: {e}")

if __name__ == "__main__":
    print("Starting OBP Consent Trace Logging Test...")

    # Run the main test
    success = asyncio.run(test_consent_trace_logging())

    # Test anonymous mode
    test_without_jwt()

    if success:
        print("\n🎉 Trace logging test completed successfully!")
        print("\nTo see these logs in production:")
        print("1. Set LOG_LEVEL=DEBUG in your environment")
        print("2. Make actual OBP API requests through the service")
        print("3. Check the application logs for DEBUG messages")
    else:
        print("\n❌ Debug logging test failed!")
        sys.exit(1)
