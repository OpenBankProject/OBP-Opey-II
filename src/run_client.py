#### ASYNC ####
import asyncio
import os
import sys

from client import AgentClient
from schema import ChatMessage


async def amain() -> None:
    # Check for command line argument first, then environment variable, then default
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = os.getenv("AGENT_BASE_URL", "http://localhost:5000")
    
    print(f"Connecting to agent service at: {base_url}")
    client = AgentClient(base_url=base_url)

    print("Chat example:")
    response = await client.ainvoke("Tell me a brief joke?")
    response.pretty_print()

    print("\nStream example:")
    async for message in client.astream("Share a quick fun fact?"):
        if isinstance(message, str):
            print(message, flush=True, end="|")
        elif isinstance(message, ChatMessage):
            print(f"\n{message.content}")
        elif isinstance(message, dict):
            # Handle streaming events like assistant_start, keep_alive, etc.
            if message.get("type") in ["assistant_start", "keep_alive"]:
                continue  # Skip these events silently
            else:
                print(f"Stream event: {message.get('type', 'unknown')}")
        else:
            print(f"ERROR: Unknown type - {type(message)}")


asyncio.run(amain())

#### SYNC ####
# Check for command line argument first, then environment variable, then default
if len(sys.argv) > 1:
    base_url = sys.argv[1]
else:
    base_url = os.getenv("AGENT_BASE_URL", "http://localhost:5000")

print(f"Connecting to agent service at: {base_url}")
client = AgentClient(base_url=base_url)

print("Chat example:")
response = client.invoke("Tell me a brief joke?")
response.pretty_print()

print("Tell me who am i :")
response = client.invoke("Can you tell me who is the current OBP User? Plz call the according obp endpoint. Only return the id for privacy reasons.")
response.pretty_print()


print("\nStream example:")
for message in client.stream("Share a quick fun fact?"):
    if isinstance(message, str):
        print(message, flush=True, end="|")
    elif isinstance(message, ChatMessage):
        print(f"\n{message.content}")
    elif isinstance(message, dict):
        # Handle streaming events like assistant_start, keep_alive, etc.
        if message.get("type") in ["assistant_start", "keep_alive"]:
            continue  # Skip these events silently
        else:
            print(f"Stream event: {message.get('type', 'unknown')}")
    else:
        print(f"ERROR: Unknown type - {type(message)}")