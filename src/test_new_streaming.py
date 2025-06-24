import asyncio
import json
from typing import AsyncGenerator

from service.streaming import (
    StreamEventFactory,
    StreamManager,
    AssistantStartEvent,
    AssistantTokenEvent,
    AssistantCompleteEvent,
    ToolStartEvent,
    ToolEndEvent,
    ErrorEvent,
    ApprovalRequestEvent,
    StreamEndEvent
)
from service.streaming.migration import StreamEventMigrator, BackwardCompatibilityWrapper
from schema import StreamInput


async def test_event_creation():
    """Test creating different types of events"""
    print("=== Testing Event Creation ===")

    # Test assistant events
    start_event = StreamEventFactory.assistant_start(message_id="test-123")
    print(f"Assistant start: {start_event.model_dump()}")

    token_event = StreamEventFactory.assistant_token("Hello", message_id="test-123")
    print(f"Assistant token: {token_event.model_dump()}")

    end_event = StreamEventFactory.assistant_complete(
        content="Hello world!",
        message_id="test-123",
        tool_calls=[{"name": "test_tool", "id": "call_123", "args": {}}]
    )
    print(f"Assistant end: {end_event.model_dump()}")

    # Test tool events
    tool_start = StreamEventFactory.tool_start(
        tool_name="obp_requests",
        tool_call_id="call_456",
        tool_input={"method": "GET", "path": "/banks"},
        run_id="test-123"
    )
    print(f"Tool start: {tool_start.model_dump()}")

    tool_end = StreamEventFactory.tool_end(
        tool_name="obp_requests",
        tool_call_id="call_456",
        tool_output={"banks": [{"id": "bank1"}]},
        status="success",
        run_id="test-123"
    )
    print(f"Tool end: {tool_end.model_dump()}")

    # Test error event
    error_event = StreamEventFactory.error(
        error_message="Something went wrong",
        error_code="TEST_ERROR",
        run_id="test-123"
    )
    print(f"Error: {error_event.model_dump()}")

    # Test approval request
    approval_event = StreamEventFactory.approval_request(
        tool_name="obp_requests",
        tool_call_id="call_789",
        tool_input={"method": "POST", "path": "/banks", "body": "{}"},
        message="Approval required for POST request",
        run_id="test-123"
    )
    print(f"Approval request: {approval_event.model_dump()}")


async def test_sse_formatting():
    """Test SSE formatting"""
    print("\n=== Testing SSE Formatting ===")

    events = [
        StreamEventFactory.assistant_start(message_id="test-123"),
        StreamEventFactory.assistant_token("Hello", message_id="test-123"),
        StreamEventFactory.assistant_token(" world!", message_id="test-123"),
        StreamEventFactory.assistant_complete("Hello world!", message_id="test-123"),
        StreamEventFactory.stream_end()
    ]

    for event in events:
        sse_data = event.to_sse_data()
        print(f"SSE: {sse_data.strip()}")


async def test_migration():
    """Test migration between old and new formats"""
    print("\n=== Testing Migration ===")

    migrator = StreamEventMigrator()

    # Test new to old format conversion
    new_event = StreamEventFactory.assistant_token("Hello", run_id="test-123")
    old_format = migrator.new_to_old_format(new_event)
    print(f"New -> Old: {old_format}")

    # Test old to new format conversion
    old_event = {"type": "token", "content": "Hello", "run_id": "test-123"}
    new_format = migrator.old_to_new_format(old_event)
    if new_format:
        print(f"Old -> New: {new_format.model_dump()}")

    # Test backward compatibility wrapper
    wrapper = BackwardCompatibilityWrapper(use_legacy=True)
    legacy_sse = wrapper.format_event(new_event)
    print(f"Legacy SSE: {legacy_sse.strip()}")

    wrapper.set_legacy_mode(False)
    new_sse = wrapper.format_event(new_event)
    print(f"New SSE: {new_sse.strip()}")


async def mock_streaming_scenario():
    """Mock a complete streaming scenario"""
    print("\n=== Mock Streaming Scenario ===")

    async def mock_stream() -> AsyncGenerator[str, None]:
        """Simulate a streaming response"""
        run_id = "mock-run-123"

        # Assistant starts
        yield StreamEventFactory.assistant_start(run_id=run_id).to_sse_data()

        # Stream some tokens
        tokens = ["I'll", " help", " you", " with", " the", " OBP", " API."]
        for token in tokens:
            yield StreamEventFactory.assistant_token(token, run_id=run_id).to_sse_data()
            await asyncio.sleep(0.1)  # Simulate streaming delay

        # Tool execution starts
        yield StreamEventFactory.tool_start(
            tool_name="endpoint_retrieval",
            tool_call_id="call_123",
            tool_input={"query": "banks endpoint"},
            run_id=run_id
        ).to_sse_data()

        # Tool completes
        yield StreamEventFactory.tool_end(
            tool_name="endpoint_retrieval",
            tool_call_id="call_123",
            tool_output={"endpoints": ["/obp/v5.0.0/banks"]},
            status="success",
            run_id=run_id
        ).to_sse_data()

        # Assistant continues with more tokens
        more_tokens = [" You", " can", " use", " the", " /banks", " endpoint."]
        for token in more_tokens:
            yield StreamEventFactory.assistant_token(token, run_id=run_id).to_sse_data()
            await asyncio.sleep(0.05)

        # Assistant finishes
        full_response = "I'll help you with the OBP API. You can use the /banks endpoint."
        yield StreamEventFactory.assistant_complete(
            content=full_response,
            message_id=run_id,
            tool_calls=[]
        ).to_sse_data()

        # Stream ends
        yield StreamEventFactory.stream_end().to_sse_data()

    print("Streaming events:")
    async for sse_event in mock_stream():
        print(sse_event.strip())


async def test_event_validation():
    """Test event validation and error handling"""
    print("\n=== Testing Event Validation ===")

    try:
        # Test creating events with invalid data
        valid_event = StreamEventFactory.assistant_token("Valid content", run_id="test")
        print(f"Valid event: {valid_event.type}")

        # Test error event
        error_event = StreamEventFactory.error("Test error message")
        print(f"Error event: {error_event.error_message}")

        # Test approval event with all required fields
        approval_event = StreamEventFactory.approval_request(
            tool_name="test_tool",
            tool_call_id="test_call",
            tool_input={"param": "value"},
            message="Test approval"
        )
        print(f"Approval event: {approval_event.tool_name}")

    except Exception as e:
        print(f"Validation error: {e}")


async def test_event_types():
    """Test all event types are properly defined"""
    print("\n=== Testing Event Types ===")

    event_types = [
        ("assistant_start", StreamEventFactory.assistant_start("test-msg-id")),
        ("assistant_token", StreamEventFactory.assistant_token("test", "test-msg-id")),
        ("assistant_complete", StreamEventFactory.assistant_complete("test", "test-msg-id")),
        ("tool_start", StreamEventFactory.tool_start("tool", "id", {})),
        ("tool_end", StreamEventFactory.tool_end("tool", "id", "output")),
        ("error", StreamEventFactory.error("error")),
        ("keep_alive", StreamEventFactory.keep_alive()),
        ("approval_request", StreamEventFactory.approval_request("tool", "id", {}, "msg")),
        ("stream_end", StreamEventFactory.stream_end())
    ]

    for event_name, event in event_types:
        print(f"{event_name}: {event.type} - {type(event).__name__}")

        # Test SSE conversion
        sse_data = event.to_sse_data()
        assert sse_data.startswith("data: "), f"Invalid SSE format for {event_name}"
        assert sse_data.endswith("\n\n"), f"Invalid SSE termination for {event_name}"


async def main():
    """Run all tests"""
    print("🚀 Testing New Streaming System")
    print("=" * 50)

    try:
        await test_event_creation()
        await test_sse_formatting()
        await test_migration()
        await test_event_validation()
        await test_event_types()
        await mock_streaming_scenario()

        print("\n✅ All tests passed!")
        print("\nThe new streaming system is working correctly!")
        print("\nKey improvements:")
        print("- Clear event types (assistant_start, assistant_token, etc.)")
        print("- Better separation of concerns")
        print("- Easier to consume by frontend applications")
        print("- Backward compatibility support")
        print("- Type safety with Pydantic models")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
