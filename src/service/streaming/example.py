"""
Example demonstrating the new streaming system for OBP-Opey-II

This example shows how to use the new event-driven streaming architecture
that replaces the previous convoluted streaming implementation.
"""

import asyncio
import json
import sys
import os
from typing import AsyncGenerator

# Add the src directory to the path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, '..', '..')
sys.path.insert(0, src_dir)

from service.streaming.events import StreamEventFactory, StreamEvent
from service.streaming.migration import BackwardCompatibilityWrapper


async def basic_streaming_example():
    """Basic example of creating and handling stream events"""
    print("=== Basic Streaming Example ===")

    run_id = "example-run-123"

    # Create different types of events
    events = [
        StreamEventFactory.assistant_start(run_id=run_id),
        StreamEventFactory.assistant_token("Hello", run_id=run_id),
        StreamEventFactory.assistant_token(" there!", run_id=run_id),
        StreamEventFactory.tool_start(
            tool_name="obp_requests",
            tool_call_id="call_456",
            tool_input={"method": "GET", "path": "/obp/v5.0.0/banks"},
            run_id=run_id
        ),
        StreamEventFactory.tool_end(
            tool_name="obp_requests",
            tool_call_id="call_456",
            tool_output={"banks": [{"id": "gh.29.uk", "name": "Demo Bank"}]},
            status="success",
            run_id=run_id
        ),
        StreamEventFactory.assistant_token(" You", run_id=run_id),
        StreamEventFactory.assistant_token(" can", run_id=run_id),
        StreamEventFactory.assistant_token(" access", run_id=run_id),
        StreamEventFactory.assistant_token(" the", run_id=run_id),
        StreamEventFactory.assistant_token(" banks!", run_id=run_id),
        StreamEventFactory.assistant_end(
            content="Hello there! You can access the banks!",
            tool_calls=[],
            run_id=run_id
        ),
        StreamEventFactory.stream_end()
    ]

    # Process events
    assistant_response = ""
    tool_outputs = {}

    for event in events:
        print(f"Event: {event.type}")

        match event.type:
            case "assistant_start":
                print("  🤖 Assistant started responding...")

            case "assistant_token":
                assistant_response += event.content
                print(f"  💬 Token: '{event.content}'")

            case "assistant_end":
                print(f"  ✅ Assistant finished: '{event.content}'")

            case "tool_start":
                print(f"  🔧 Tool '{event.tool_name}' starting...")
                print(f"      Input: {event.tool_input}")

            case "tool_end":
                tool_outputs[event.tool_call_id] = event.tool_output
                print(f"  ✅ Tool '{event.tool_name}' completed ({event.status})")
                print(f"      Output: {event.tool_output}")

            case "stream_end":
                print("  🏁 Stream ended")

        # Show SSE format
        sse_data = event.to_sse_data()
        print(f"      SSE: {sse_data.strip()}")
        print()


async def frontend_integration_example():
    """Example showing how frontend applications can handle events"""
    print("=== Frontend Integration Example ===")

    async def simulate_sse_stream() -> AsyncGenerator[str, None]:
        """Simulate SSE stream from server"""
        events = [
            StreamEventFactory.assistant_start(run_id="frontend-123"),
            StreamEventFactory.assistant_token("I'll help you with the OBP API.", run_id="frontend-123"),
            StreamEventFactory.tool_start(
                tool_name="endpoint_retrieval",
                tool_call_id="search_001",
                tool_input={"query": "account balance endpoint"},
                run_id="frontend-123"
            ),
            StreamEventFactory.tool_end(
                tool_name="endpoint_retrieval",
                tool_call_id="search_001",
                tool_output={
                    "endpoints": [
                        {"path": "/obp/v5.0.0/banks/BANK_ID/accounts/ACCOUNT_ID", "method": "GET"}
                    ]
                },
                status="success",
                run_id="frontend-123"
            ),
            StreamEventFactory.assistant_token(" You can use the account endpoint.", run_id="frontend-123"),
            StreamEventFactory.assistant_end(
                content="I'll help you with the OBP API. You can use the account endpoint.",
                run_id="frontend-123"
            ),
            StreamEventFactory.stream_end()
        ]

        for event in events:
            yield event.to_sse_data()
            await asyncio.sleep(0.5)  # Simulate streaming delay

    # Frontend event handler
    class FrontendEventHandler:
        def __init__(self):
            self.current_response = ""
            self.active_tools = {}
            self.completed_tools = {}

        def handle_sse_line(self, line: str):
            """Handle a single SSE line (like a frontend would)"""
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    self.on_stream_end()
                    return

                try:
                    event_data = json.loads(data)
                    self.handle_event(event_data)
                except json.JSONDecodeError as e:
                    print(f"Error parsing SSE data: {e}")

        def handle_event(self, event_data):
            """Handle parsed event data"""
            event_type = event_data.get("type")

            match event_type:
                case "assistant_start":
                    self.on_assistant_start(event_data)
                case "assistant_token":
                    self.on_assistant_token(event_data)
                case "assistant_end":
                    self.on_assistant_end(event_data)
                case "tool_start":
                    self.on_tool_start(event_data)
                case "tool_end":
                    self.on_tool_end(event_data)
                case "error":
                    self.on_error(event_data)
                case _:
                    print(f"Unknown event type: {event_type}")

        def on_assistant_start(self, event):
            print("🤖 Assistant is thinking...")
            self.current_response = ""

        def on_assistant_token(self, event):
            token = event["content"]
            self.current_response += token
            print(f"💬 {token}", end="", flush=True)

        def on_assistant_end(self, event):
            print("\n✅ Assistant response complete")
            print(f"Full response: {event['content']}")

        def on_tool_start(self, event):
            tool_name = event["tool_name"]
            tool_call_id = event["tool_call_id"]
            self.active_tools[tool_call_id] = tool_name
            print(f"\n🔧 Starting {tool_name}...")
            print(f"   Input: {event['tool_input']}")

        def on_tool_end(self, event):
            tool_call_id = event["tool_call_id"]
            tool_name = event["tool_name"]
            status = event["status"]

            if tool_call_id in self.active_tools:
                del self.active_tools[tool_call_id]

            self.completed_tools[tool_call_id] = event["tool_output"]
            print(f"\n✅ {tool_name} completed ({status})")
            print(f"   Output: {event['tool_output']}")

        def on_error(self, event):
            print(f"\n❌ Error: {event['error_message']}")
            if event.get("error_code"):
                print(f"   Code: {event['error_code']}")

        def on_stream_end(self):
            print("\n🏁 Stream completed")
            print(f"Final response: {self.current_response}")
            print(f"Tools used: {len(self.completed_tools)}")

    # Simulate frontend handling
    handler = FrontendEventHandler()

    async for sse_line in simulate_sse_stream():
        handler.handle_sse_line(sse_line.strip())


async def backward_compatibility_example():
    """Example showing backward compatibility with legacy format"""
    print("=== Backward Compatibility Example ===")

    # Create new format events
    new_events = [
        StreamEventFactory.assistant_token("Hello world!", run_id="compat-123"),
        StreamEventFactory.tool_start(
            tool_name="obp_requests",
            tool_call_id="legacy_call",
            tool_input={"method": "GET", "path": "/banks"},
            run_id="compat-123"
        ),
        StreamEventFactory.error("Something went wrong", error_code="TEST_ERROR")
    ]

    # Show new format
    print("New Format Events:")
    for event in new_events:
        print(f"  {event.model_dump()}")

    print("\nConverted to Legacy Format:")
    wrapper = BackwardCompatibilityWrapper(use_legacy=True)

    for event in new_events:
        legacy_sse = wrapper.format_event(event)
        print(f"  {legacy_sse.strip()}")


async def approval_workflow_example():
    """Example showing approval workflow for dangerous operations"""
    print("=== Approval Workflow Example ===")

    run_id = "approval-123"

    # Simulate a workflow that requires approval
    events = [
        StreamEventFactory.assistant_start(run_id=run_id),
        StreamEventFactory.assistant_token("I'll create a new bank account for you.", run_id=run_id),
        StreamEventFactory.approval_request(
            tool_name="obp_requests",
            tool_call_id="dangerous_call_789",
            tool_input={
                "method": "POST",
                "path": "/obp/v5.0.0/banks/gh.29.uk/accounts",
                "body": '{"account_type": "CURRENT"}'
            },
            message="This operation will create a new bank account. Do you want to proceed?",
            run_id=run_id
        )
    ]

    for event in events:
        match event.type:
            case "assistant_start":
                print("🤖 Assistant starting...")
            case "assistant_token":
                print(f"💬 {event.content}")
            case "approval_request":
                print(f"\n⚠️  APPROVAL REQUIRED")
                print(f"   Tool: {event.tool_name}")
                print(f"   Operation: {event.tool_input['method']} {event.tool_input['path']}")
                print(f"   Message: {event.message}")

                # Simulate user approval
                user_choice = "approve"  # In real app, this would come from UI
                print(f"   User choice: {user_choice}")

                if user_choice == "approve":
                    # Continue with tool execution
                    continuation_events = [
                        StreamEventFactory.tool_start(
                            tool_name=event.tool_name,
                            tool_call_id=event.tool_call_id,
                            tool_input=event.tool_input,
                            run_id=run_id
                        ),
                        StreamEventFactory.tool_end(
                            tool_name=event.tool_name,
                            tool_call_id=event.tool_call_id,
                            tool_output={"account_id": "new_account_123", "status": "created"},
                            status="success",
                            run_id=run_id
                        ),
                        StreamEventFactory.assistant_token(" Account created successfully!", run_id=run_id),
                        StreamEventFactory.assistant_end(
                            content="I'll create a new bank account for you. Account created successfully!",
                            run_id=run_id
                        )
                    ]

                    for cont_event in continuation_events:
                        match cont_event.type:
                            case "tool_start":
                                print(f"🔧 Executing approved operation...")
                            case "tool_end":
                                print(f"✅ Operation completed: {cont_event.tool_output}")
                            case "assistant_token":
                                print(f"💬 {cont_event.content}")
                            case "assistant_end":
                                print(f"✅ Final response: {cont_event.content}")
                else:
                    print("❌ Operation cancelled by user")


async def main():
    """Run all examples"""
    print("🚀 OBP-Opey-II New Streaming System Examples")
    print("=" * 60)

    await basic_streaming_example()
    print("\n" + "=" * 60 + "\n")

    await frontend_integration_example()
    print("\n" + "=" * 60 + "\n")

    await backward_compatibility_example()
    print("\n" + "=" * 60 + "\n")

    await approval_workflow_example()
    print("\n" + "=" * 60)

    print("\n✅ All examples completed!")
    print("\nKey takeaways:")
    print("• Events are strongly typed and self-describing")
    print("• Easy to handle in frontend applications")
    print("• Backward compatibility is maintained")
    print("• Approval workflows are clearly defined")
    print("• Error handling is structured and informative")


if __name__ == "__main__":
    asyncio.run(main())
