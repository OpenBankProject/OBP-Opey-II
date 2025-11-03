#!/usr/bin/env python3
"""
Test script to verify user_message_confirmed event is emitted
"""
import requests
import json

# Test endpoint
url = "http://localhost:5000/stream"

# Create a session first
session_response = requests.post(
    "http://localhost:5000/create-session",
    headers={"Consent-JWT": "test"},
    cookies={}
)
print(f"Session created: {session_response.status_code}")
cookies = session_response.cookies

# Send a message and check for user_message_confirmed event
payload = {
    "message": "Hello, test message!",
    "thread_id": "test-thread-123"
}

print("\nSending message and watching for events...\n")

response = requests.post(
    url,
    json=payload,
    cookies=cookies,
    stream=True
)

found_user_confirmed = False
user_confirmed_event = None

for line in response.iter_lines():
    if line:
        decoded_line = line.decode('utf-8')
        print(decoded_line)
        
        # Look for user_message_confirmed event
        if decoded_line.startswith('data: '):
            try:
                event_data = json.loads(decoded_line[6:])  # Remove 'data: ' prefix
                if event_data.get('type') == 'user_message_confirmed':
                    found_user_confirmed = True
                    user_confirmed_event = event_data
                    print(f"\n✅ Found user_message_confirmed event!")
                    print(f"   Message ID: {event_data.get('message_id')}")
                    print(f"   Content: {event_data.get('content')}\n")
            except json.JSONDecodeError:
                pass
        
        # Stop after stream ends
        if decoded_line == 'data: [DONE]':
            break

print("\n" + "="*50)
if found_user_confirmed:
    print("✅ SUCCESS: user_message_confirmed event was emitted")
    print(f"Full event: {json.dumps(user_confirmed_event, indent=2)}")
else:
    print("❌ FAILURE: user_message_confirmed event was NOT emitted")
print("="*50)
