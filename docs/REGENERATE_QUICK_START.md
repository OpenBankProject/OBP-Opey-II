# Regenerate Response API

## What It Does

Regenerates the AI's response starting from a specific message in your conversation.

**Use this when:**
- User wants a different answer to their question
- Response wasn't satisfactory
- User wants to try a different conversation path

## Endpoint

```
POST /stream/{thread_id}/regenerate?message_id={message_id}
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thread_id` | string | Yes | Your conversation thread ID |
| `message_id` | string | Yes | ID of the message to regenerate from |

### Authentication

Requires session cookie (same as other endpoints).

### Response

Server-Sent Events (SSE) stream - same format as `/stream` endpoint.

## How It Works

You specify a message ID, and everything **after** that message gets regenerated.

**Example conversation:**
```
1. User: "Hello"                    (id: msg-1)
2. Assistant: "Hi there!"           (id: msg-2)
3. User: "What is OBP?"             (id: msg-3) ← You specify this
4. Assistant: "OBP is..."           (id: msg-4) ← Gets removed
5. Assistant: [new response]                    ← Gets generated
```

## Quick Example

```javascript
// User clicks "regenerate" on their message
const response = await fetch(
  '/stream/my-thread-123/regenerate?message_id=msg-3',
  {
    method: 'POST',
    credentials: 'include'
  }
);

// Handle SSE stream (same as /stream endpoint)
const reader = response.body.getReader();
// ... process streaming response
```

## Response Headers

```
X-Thread-ID: {thread_id}
X-Regenerated: true
X-Regenerated-From: {message_id}
```

## Error Responses

| Status | Meaning |
|--------|---------|
| `404` | Message ID not found or no conversation history |
| `400` | Message is already the last message (nothing to regenerate) |
| `403` | Authentication required |
| `500` | Internal server error |

## Example Usage

### JavaScript/Fetch
```javascript
const response = await fetch(
  '/stream/thread-123/regenerate?message_id=msg-456',
  {
    method: 'POST',
    credentials: 'include'
  }
);

// Read SSE stream
const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const text = decoder.decode(value);
  // Parse SSE format: "data: {...}\n\n"
  console.log(text);
}
```

### cURL
```bash
curl -X POST \
  'https://your-api.com/stream/thread-123/regenerate?message_id=msg-456' \
  -H 'Cookie: session=your-session-cookie' \
  --no-buffer
```

### Python
```python
import httpx

async with httpx.AsyncClient() as client:
    async with client.stream(
        'POST',
        'https://your-api.com/stream/thread-123/regenerate',
        params={'message_id': 'msg-456'},
        cookies={'session': 'your-session-cookie'}
    ) as response:
        async for line in response.aiter_lines():
            print(line)
```

## Notes

- Requires valid session (authenticate first)
- Returns same SSE format as `/stream` endpoint
- Counts as a new request for rate limiting
- Message IDs must be from the same thread
