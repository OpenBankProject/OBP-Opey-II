# Streaming System Refactor

This directory contains the refactored streaming system for OBP-Opey-II, designed to follow SOLID principles and provide cleaner, more maintainable event handling.

## Overview

The new streaming system replaces the previous convoluted `_process_stream_event` function with a clean, event-driven architecture that provides:

- **Clear event types** for better frontend integration
- **Type safety** using Pydantic models
- **Simplified event structure** without unnecessary run_id fields
- **Single Responsibility Principle** with dedicated processors
- **Backward compatibility** for existing clients
- **Easy extensibility** for new event types

## Architecture

```
streaming/
├── events.py           # Event definitions and factory
├── processors.py       # Event processors with single responsibilities
├── stream_manager.py   # Main streaming interface
├── migration.py        # Backward compatibility utilities
└── __init__.py         # Module exports
```

## Event Types

The new system provides clear, semantic event types:

### Assistant Events
- `assistant_start` - Emitted when the assistant begins responding
- `assistant_token` - Individual tokens streamed from the assistant
- `assistant_end` - Emitted when the assistant completes its response

### Tool Events
- `tool_start` - Emitted when a tool execution begins
- `tool_token` - Tokens streamed during tool execution (if supported)
- `tool_end` - Emitted when a tool execution completes

### System Events
- `error` - Emitted when an error occurs
- `approval_request` - Emitted when human approval is required
- `keep_alive` - Connection keepalive events
- `stream_end` - Emitted when the stream terminates

## Usage

### Basic Usage

```python
from service.streaming import StreamManager, StreamEventFactory

# Create a stream manager
stream_manager = StreamManager(opey_session)

# Stream events
async for event in stream_manager.stream_response(stream_input, config):
    # Handle different event types
    match event.type:
        case "assistant_token":
            print(event.content, end="", flush=True)
        case "tool_start":
            print(f"Starting tool: {event.tool_name}")
        case "tool_end":
            print(f"Tool completed: {event.tool_output}")
        case "error":
            print(f"Error: {event.error_message}")

    # Convert to SSE format
    sse_data = event.to_sse_data()
    yield sse_data
```

### Event Creation

```python
from service.streaming import StreamEventFactory

# Create events using the factory
start_event = StreamEventFactory.assistant_start()
token_event = StreamEventFactory.assistant_token("Hello")
tool_event = StreamEventFactory.tool_start(
    tool_name="obp_requests",
    tool_call_id="call_456",
    tool_input={"method": "GET", "path": "/banks"}
)
```

### Client Integration

The client automatically handles the new event types while maintaining backward compatibility:

```python
# The client now returns typed events
async for event in client.astream("Hello"):
    if isinstance(event, dict):
        # Handle new event types
        if event.get("type") == "tool_start":
            print(f"Tool starting: {event['tool_name']}")
    elif isinstance(event, str):
        # Token content
        print(event, end="")
    elif isinstance(event, ChatMessage):
        # Complete messages
        event.pretty_print()
```

## Migration and Backward Compatibility

### Legacy Format Support

The system includes migration utilities for backward compatibility:

```python
from service.streaming.migration import BackwardCompatibilityWrapper

# Use legacy format for old clients
wrapper = BackwardCompatibilityWrapper(use_legacy=True)
legacy_sse = wrapper.format_event(new_event)

# Or use new format
wrapper.set_legacy_mode(False)
new_sse = wrapper.format_event(new_event)
```

### Migration Utilities

```python
from service.streaming.migration import StreamEventMigrator

migrator = StreamEventMigrator()

# Convert new events to old format
old_format = migrator.new_to_old_format(new_event)

# Convert old events to new format
new_event = migrator.old_to_new_format(old_event)
```

## Event Format Comparison

### Old Format
```json
{
  "type": "token",
  "content": "Hello"
}

{
  "type": "message",
  "content": {
    "type": "ai",
    "content": "Complete response",
    "tool_calls": []
  }
}
```

### New Format
```json
{
  "type": "assistant_token",
  "content": "Hello",
  "timestamp": null
}

{
  "type": "assistant_end",
  "content": "Complete response",
  "tool_calls": [],
  "timestamp": null
}

{
  "type": "tool_start",
  "tool_name": "obp_requests",
  "tool_call_id": "call_456",
  "tool_input": {"method": "GET"},
  "timestamp": null
}
```

## Benefits

### For Frontend Applications

1. **Predictable Events**: Clear event types make it easier to handle different streaming phases
2. **Better UX**: Can show tool execution progress with `tool_start`/`tool_end` events
3. **Error Handling**: Dedicated error events with structured information
4. **Type Safety**: TypeScript/JavaScript clients can use proper typing

### For Backend Development

1. **SOLID Principles**: Each processor has a single responsibility
2. **Maintainability**: Clear separation between event types and processing logic
3. **Extensibility**: Easy to add new event types and processors
4. **Testing**: Individual processors can be unit tested in isolation

### Performance

1. **Efficient Processing**: Events are processed only by relevant processors
2. **Memory Efficiency**: Cleaner event objects with only necessary data
3. **Network Efficiency**: More compact SSE payloads

## Extending the System

### Adding New Event Types

1. Define the event in `events.py`:
```python
class CustomEvent(BaseStreamEvent):
    type: Literal["custom"] = "custom"
    custom_data: str
    
    def to_sse_data(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"
```

2. Add factory method:
```python
@staticmethod
def custom_event(custom_data: str) -> CustomEvent:
    return CustomEvent(custom_data=custom_data)
```

3. Update the union type:
```python
StreamEvent = Union[
    # ... existing events
    CustomEvent
]
```

### Adding New Processors

1. Create a processor in `processors.py`:
```python
class CustomEventProcessor(BaseEventProcessor):
    async def process(self, event: LangGraphStreamEvent) -> AsyncGenerator[StreamEvent, None]:
        if self._should_process(event):
            yield StreamEventFactory.custom_event("data")
```

2. Add to orchestrator:
```python
self.processors = [
    # ... existing processors
    CustomEventProcessor(run_id, stream_input)
]
```

## Error Handling

The system provides structured error handling:

```python
# Errors are automatically converted to error events
try:
    # Process stream event
    pass
except Exception as e:
    yield StreamEventFactory.error(
        error_message=str(e),
        error_code="processing_error",
        details={"context": "additional_info"}
    )
```

## Testing

The streaming system includes comprehensive tests that can be run independently:

```bash
cd src
python -m pytest test_streaming_system.py
```

## Migration Guide

### For Frontend Applications

1. **Update event handling**:
   - Replace `event.type === "token"` with `event.type === "assistant_token"`
   - Replace `event.type === "message"` with `event.type === "assistant_end"`
   - Add handlers for new event types like `tool_start` and `tool_end`

2. **Use structured data**:
   - Access `event.content` directly instead of `event.content.content`
   - Use `event.tool_name` instead of parsing from message content
   - No need to track `run_id` - use `thread_id` for conversation persistence

3. **Enhanced UX**:
   - Show tool execution progress with `tool_start`/`tool_end` events
   - Display better error messages with structured `error` events
   - Cleaner event structure without unnecessary fields

### For Backend Development

1. **Replace old streaming logic**:
   - Use `StreamManager` instead of `opey_message_generator`
   - Use event processors instead of complex conditional logic

2. **Update imports**:
   ```python
   from service.streaming import StreamManager
   from service.streaming.events import StreamEventFactory
   ```

3. **Modernize event emission**:
   ```python
   # Old way
   yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
   
   # New way
   event = StreamEventFactory.assistant_token(token)
   yield event.to_sse_data()
   ```

## Future Improvements

1. **Node-based routing**: Use LangGraph's `langgraph_node` metadata for even simpler processing
2. **Event Filtering**: Allow clients to subscribe to specific event types
3. **Event Batching**: Batch multiple events for efficiency
4. **WebSocket Support**: Extend beyond SSE to WebSocket connections
5. **Event Persistence**: Store events for replay and debugging using thread_id

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure you're importing from the new streaming module
2. **Type Errors**: Make sure you're using the correct event types
3. **Backward Compatibility**: Use migration utilities for legacy clients

### Debug Mode

Enable debug logging to see event processing:

```python
import logging
logging.getLogger('opey.streaming').setLevel(logging.DEBUG)
```

### Performance Monitoring

Monitor event processing performance:

```python
import time

start_time = time.time()
async for event in stream_manager.stream_response(...):
    processing_time = time.time() - start_time
    logger.debug(f"Event {event.type} processed in {processing_time:.3f}s")
    start_time = time.time()
```
