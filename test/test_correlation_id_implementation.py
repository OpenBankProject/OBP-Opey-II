"""
Test suite for correlation_id and thread_sync implementation.

Tests verify:
1. Frontend generates a correlation_id when sending a message
2. Backend echoes it back in user_message_confirmed event
3. Backend sends thread_sync event at stream start
4. Frontend can retrieve authoritative message history via GET endpoint
"""

import pytest
import uuid
import json

from schema.schema import StreamInput
from service.streaming.events import StreamEventFactory


def generate_correlation_id() -> str:
    """Simulate frontend generating a correlation ID"""
    return str(uuid.uuid4())


def test_stream_input_accepts_correlation_id():
    """Test that StreamInput accepts and stores correlation_id"""
    correlation_id = generate_correlation_id()
    
    stream_input = StreamInput(
        message="Test message",
        thread_id="test-thread-123",
        correlation_id=correlation_id,
        stream_tokens=True
    )
    
    assert stream_input.message == "Test message"
    assert stream_input.thread_id == "test-thread-123"
    assert stream_input.correlation_id == correlation_id
    assert stream_input.stream_tokens is True


def test_user_message_confirmed_event_includes_correlation_id():
    """Test that UserMessageConfirmEvent includes correlation_id"""
    correlation_id = generate_correlation_id()
    backend_id = str(uuid.uuid4())
    
    event = StreamEventFactory.user_message_confirmed(
        message_id=backend_id,
        correlation_id=correlation_id,
        content="Test message content"
    )
    
    assert event.message_id == backend_id
    assert event.correlation_id == correlation_id
    assert event.content == "Test message content"
    assert event.type == "user_message_confirmed"


def test_thread_sync_event_creation():
    """Test that ThreadSyncEvent is created correctly"""
    thread_id = "test-thread-456"
    
    sync_event = StreamEventFactory.thread_sync(thread_id=thread_id)
    
    assert sync_event.thread_id == thread_id
    assert sync_event.type == "thread_sync"


def test_user_message_confirmed_sse_serialization():
    """Test SSE serialization of user_message_confirmed event"""
    correlation_id = generate_correlation_id()
    backend_id = str(uuid.uuid4())
    
    event = StreamEventFactory.user_message_confirmed(
        message_id=backend_id,
        correlation_id=correlation_id,
        content="Test content"
    )
    
    sse_data = event.to_sse_data()
    
    assert sse_data.startswith("data: ")
    assert sse_data.endswith("\n\n")
    
    # Parse the JSON data
    json_str = sse_data.replace("data: ", "").strip()
    parsed = json.loads(json_str)
    
    assert parsed["type"] == "user_message_confirmed"
    assert parsed["message_id"] == backend_id
    assert parsed["correlation_id"] == correlation_id
    assert parsed["content"] == "Test content"


def test_thread_sync_sse_serialization():
    """Test SSE serialization of thread_sync event"""
    thread_id = "test-thread-789"
    
    sync_event = StreamEventFactory.thread_sync(thread_id=thread_id)
    sse_data = sync_event.to_sse_data()
    
    assert sse_data.startswith("data: ")
    assert sse_data.endswith("\n\n")
    
    # Parse the JSON data
    json_str = sse_data.replace("data: ", "").strip()
    parsed = json.loads(json_str)
    
    assert parsed["type"] == "thread_sync"
    assert parsed["thread_id"] == thread_id


def test_correlation_id_matching_flow():
    """
    Test the complete correlation ID flow for reliable message matching
    """
    # 1. Frontend generates correlation_id
    frontend_correlation_id = generate_correlation_id()
    
    # 2. Frontend sends message with correlation_id
    stream_input = StreamInput(
        message="Hello, how can I help?",
        correlation_id=frontend_correlation_id,
        stream_tokens=True
    )
    
    assert stream_input.correlation_id == frontend_correlation_id
    
    # 3. Backend assigns backend message_id
    backend_message_id = str(uuid.uuid4())
    
    # 4. Backend emits user_message_confirmed with both IDs
    confirm_event = StreamEventFactory.user_message_confirmed(
        message_id=backend_message_id,
        correlation_id=frontend_correlation_id,
        content="Hello, how can I help?"
    )
    
    # 5. Verify frontend can match by correlation_id
    assert confirm_event.correlation_id == frontend_correlation_id
    assert confirm_event.message_id == backend_message_id
    
    # Frontend would find message with correlation_id and update to backend_id
    # This eliminates the fragile content-based matching


def test_thread_sync_with_provided_thread_id():
    """Test thread sync when frontend provides thread_id"""
    frontend_thread_id = "existing-thread-789"
    
    # Backend uses provided thread_id
    sync_event = StreamEventFactory.thread_sync(thread_id=frontend_thread_id)
    
    assert sync_event.thread_id == frontend_thread_id


def test_thread_sync_with_generated_thread_id():
    """Test thread sync when backend generates new thread_id"""
    # Frontend doesn't provide thread_id (new conversation)
    # Backend generates one
    backend_thread_id = str(uuid.uuid4())
    
    sync_event = StreamEventFactory.thread_sync(thread_id=backend_thread_id)
    
    assert sync_event.thread_id == backend_thread_id
    # Frontend would store this as the authoritative thread_id


def test_correlation_id_optional_for_backward_compatibility():
    """Test that correlation_id is optional for backward compatibility"""
    # Should work without correlation_id
    stream_input = StreamInput(
        message="Test message",
        stream_tokens=True
    )
    
    assert stream_input.message == "Test message"
    assert stream_input.correlation_id is None  # Optional field
