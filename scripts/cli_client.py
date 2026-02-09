#!/usr/bin/env python3
"""
CLI test client for Opey agent.

Connects to the Opey service, creates a session, and provides an interactive
chat loop with support for approval and consent flows via SSE streaming.

Usage:
    python scripts/cli_client.py [--base-url http://localhost:8000] [--consent-id <jwt>] [--bearer-token <token>]
"""
import argparse
import asyncio
import json
import sys
import httpx

# SSE line parser
def parse_sse_events(text: str):
    """Parse SSE text into individual event data payloads."""
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            if payload == "[DONE]":
                events.append({"type": "stream_end"})
            else:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


class OpeyCliClient:
    """Interactive CLI client for the Opey agent service."""

    def __init__(self, base_url: str, consent_id: str | None = None, bearer_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.consent_id = consent_id
        self.bearer_token = bearer_token
        self.thread_id: str | None = None
        self.cookies: dict = {}

    async def create_session(self) -> bool:
        """Create a session (authenticated or anonymous)."""
        headers = {}
        if self.consent_id:
            headers["Consent-Id"] = self.consent_id
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        async with httpx.AsyncClient(base_url=self.base_url, follow_redirects=True) as client:
            resp = await client.post("/create-session", headers=headers)
            if resp.status_code != 200:
                print(f"[ERROR] Failed to create session: {resp.status_code} {resp.text}")
                return False
            self.cookies = dict(resp.cookies)
            data = resp.json()
            print(f"[SESSION] {data.get('session_type', 'unknown')} session created")
            return True

    async def stream_message(self, message: str) -> None:
        """Send a message and stream the response, handling interrupts."""
        payload = {
            "message": message,
            "thread_id": self.thread_id,
            "stream_tokens": True,
        }

        await self._stream_request("/stream", payload)

    async def send_approval(self, approval_data: dict) -> None:
        """Send an approval/consent response and stream the continuation."""
        if not self.thread_id:
            print("[ERROR] No thread_id — cannot send approval")
            return

        await self._stream_request(f"/approval/{self.thread_id}", approval_data)

    async def _stream_request(self, path: str, payload: dict) -> None:
        """POST to an SSE endpoint and process the streamed events."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            cookies=self.cookies,
            timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
        ) as client:
            async with client.stream("POST", path, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    print(f"[ERROR] {resp.status_code}: {body.decode()}")
                    return

                # Update cookies from response
                self.cookies.update(dict(resp.cookies))

                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    # Process complete SSE lines
                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        events = parse_sse_events(event_block)
                        for event in events:
                            await self._handle_event(event)

                # Process remaining buffer
                if buffer.strip():
                    events = parse_sse_events(buffer)
                    for event in events:
                        await self._handle_event(event)

    async def _handle_event(self, event: dict) -> None:
        """Handle a single SSE event."""
        event_type = event.get("type", "")

        match event_type:
            case "thread_sync":
                self.thread_id = event.get("thread_id")

            case "assistant_start":
                pass  # silent

            case "assistant_token":
                print(event.get("content", ""), end="", flush=True)

            case "assistant_complete":
                print()  # newline after tokens

            case "tool_start":
                print(f"\n  [TOOL] {event.get('tool_name')} ...")

            case "tool_complete":
                status = event.get("status", "?")
                name = event.get("tool_name", "?")
                print(f"  [TOOL] {name} → {status}")

            case "approval_request":
                await self._handle_approval_request(event)

            case "batch_approval_request":
                await self._handle_batch_approval(event)

            case "consent_request":
                await self._handle_consent_request(event)

            case "error":
                print(f"\n[ERROR] {event.get('error_message')}")

            case "stream_end":
                pass  # silent

            case "user_message_confirmed":
                pass  # silent

            case "keep_alive":
                pass

            case _:
                pass  # ignore unknown events

    # ---- Interactive interrupt handlers ----

    async def _handle_approval_request(self, event: dict) -> None:
        """Prompt user for tool call approval."""
        tool_name = event.get("tool_name", "?")
        tool_call_id = event.get("tool_call_id", "")
        tool_input = event.get("tool_input", {})
        levels = event.get("available_approval_levels", ["once"])

        print(f"\n{'='*60}")
        print(f"  APPROVAL REQUIRED: {tool_name}")
        print(f"  Input: {json.dumps(tool_input, indent=2)}")
        print(f"  Levels: {levels}")
        print(f"{'='*60}")

        choice = input("  Approve? (y/n) [y]: ").strip().lower()
        approved = choice != "n"

        level = "once"
        if approved and len(levels) > 1:
            level = input(f"  Level ({'/'.join(levels)}) [once]: ").strip() or "once"

        approval_data = {
            "approval": "approve" if approved else "deny",
            "level": level,
            "tool_call_id": tool_call_id,
        }
        await self.send_approval(approval_data)

    async def _handle_batch_approval(self, event: dict) -> None:
        """Prompt user for batch tool call approval."""
        tool_calls = event.get("tool_calls", [])
        print(f"\n{'='*60}")
        print(f"  BATCH APPROVAL REQUIRED ({len(tool_calls)} tools)")
        for i, tc in enumerate(tool_calls):
            print(f"    [{i+1}] {tc.get('tool_name', '?')}: {json.dumps(tc.get('tool_args', {}))}")
        print(f"{'='*60}")

        choice = input("  Approve all? (y/n) [y]: ").strip().lower()

        decisions = {}
        for tc in tool_calls:
            tcid = tc.get("tool_call_id", "")
            decisions[tcid] = {
                "approved": choice != "n",
                "level": "once",
            }

        approval_data = {"batch_decisions": decisions}
        await self.send_approval(approval_data)

    async def _handle_consent_request(self, event: dict) -> None:
        """Prompt user for consent JWT."""
        tool_name = event.get("tool_name", "?")
        operation_id = event.get("operation_id", "?")
        required_roles = event.get("required_roles", [])

        print(f"\n{'='*60}")
        print(f"  CONSENT REQUIRED")
        print(f"  Tool:      {tool_name}")
        print(f"  Operation: {operation_id}")
        print(f"  Roles:     {json.dumps(required_roles, indent=2)}")
        print(f"{'='*60}")
        print("  Paste a Consent-JWT to authorize, or press Enter to deny.")

        consent_jwt = input("  Consent-JWT: ").strip()

        if consent_jwt:
            approval_data = {"consent_jwt": consent_jwt}
        else:
            # Deny — send empty approval with no consent_jwt
            # The consent_check_node will treat missing jwt as denial
            approval_data = {"consent_jwt": None}

        await self.send_approval(approval_data)


async def main():
    parser = argparse.ArgumentParser(description="Opey CLI Client")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Base URL of the Opey service")
    parser.add_argument("--consent-id", default=None, help="OBP Consent-Id for authenticated session")
    parser.add_argument("--bearer-token", default=None, help="Bearer token for MCP server auth")
    args = parser.parse_args()

    client = OpeyCliClient(
        base_url=args.base_url,
        consent_id=args.consent_id,
        bearer_token=args.bearer_token,
    )

    if not await client.create_session():
        sys.exit(1)

    print("\nOpey CLI — type your message, or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break

        await client.stream_message(user_input)
        print()  # blank line between turns


if __name__ == "__main__":
    asyncio.run(main())
