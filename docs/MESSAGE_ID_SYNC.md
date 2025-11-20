# Message ID Synchronization Between Frontend and Backend

## Problem

The frontend was generating its own message IDs using `uuidv4()` when displaying messages, while the backend was using different IDs assigned by LangChain. This caused a mismatch when trying to use message IDs in API calls (e.g., the regenerate endpoint).

Example error:
```
Message ID 3d02d801-1bd5-4d14-a5db-a0d5cd44070e not found in messages: 
['b0cfa23b-7461-4c8f-a832-a8ae2b045616', 'run-3364a32b-5ae5-41c6-9568-503a1aabeecf']
```

## Solution

**Use backend-assigned message IDs in the frontend** instead of generating new ones.

### Backend Changes (Already Implemented)

1. **New Event Type**: Added `user_message_confirmed` event in `/src/service/streaming/events.py`
   - Emitted when backend accepts a user message
   - Contains the backend-assigned message ID
   - Allows frontend to sync its message with backend's ID

2. **Event Emission**: Updated `/src/service/streaming/stream_manager.py`
   - Emits `user_message_confirmed` after accepting user message
   - Provides both message ID and content for frontend sync

### Frontend Changes Required

#### 1. Add Handler for New Event Type

In your `ChatController.ts` (or similar), add a new case in the stream event handler:

```typescript
switch (event.type) {
    // ... existing cases ...
    
    case 'user_message_confirmed':
        logger.debug(`User message confirmed with backend ID: ${event.messageId}`);
        // Update or add the user message with the backend-assigned ID
        state.syncUserMessage(event.messageId, event.content);
        break;
        
    // ... other cases ...
}
```

#### 2. Update Message Sending Logic

**Current (incorrect) implementation:**
```typescript
send(text: string): Promise<void> {
    const msg: UserMessage = {
        id: uuidv4(),  // ❌ Frontend generates its own ID
        role: 'user',
        message: text,
        timestamp: new Date()
    };
    this.state.addMessage(msg);
    // ... rest of code
}
```

**Fixed implementation - Option A (Optimistic with Sync):**
```typescript
send(text: string): Promise<void> {
    // Add message with temporary ID
    const tempId = `temp-${uuidv4()}`;
    const msg: UserMessage = {
        id: tempId,
        role: 'user',
        message: text,
        timestamp: new Date(),
        isPending: true  // Mark as pending confirmation
    };
    this.state.addMessage(msg);
    
    // Backend will send user_message_confirmed event with real ID
    // The event handler will update this message with the backend ID
    
    return this.service.send(msg, this.state.getThreadId());
}
```

**Fixed implementation - Option B (Wait for Backend):**
```typescript
send(text: string): Promise<void> {
    // Just send to backend - don't add to state yet
    // The user_message_confirmed event will add it with correct ID
    
    // Add a loading indicator instead
    this.state.setUserMessagePending(text);
    
    return this.service.send({ message: text }, this.state.getThreadId());
}
```

#### 3. Add State Management Method

In your `ChatState.ts`:

**For Option A (Sync with backend ID):**
```typescript
/**
 * Sync a user message with backend-assigned ID.
 * Updates temporary ID to backend ID.
 */
syncUserMessage(backendId: string, content: string): void {
    // Find message by content (since temp ID won't match)
    const index = this.messages.findIndex(
        msg => msg.role === 'user' && 
               msg.message === content && 
               msg.isPending === true
    );
    
    if (index !== -1) {
        // Update with backend ID and mark as confirmed
        this.messages[index].id = backendId;
        this.messages[index].isPending = false;
        this.messages = [...this.messages]; // Trigger reactivity
        this.emit();
    } else {
        // Backend sent confirmation but we don't have the message yet
        // Add it now with the backend ID
        this.addMessage({
            id: backendId,
            role: 'user',
            message: content,
            timestamp: new Date(),
            isPending: false
        });
    }
}
```

**For Option B (Add message when confirmed):**
```typescript
/**
 * Add user message with backend-assigned ID.
 */
syncUserMessage(backendId: string, content: string): void {
    // Remove pending indicator
    this.clearUserMessagePending();
    
    // Add message with backend ID
    this.addMessage({
        id: backendId,
        role: 'user',
        message: content,
        timestamp: new Date()
    });
}
```

## Event Flow

### Current Flow (Broken)
```
1. User types message
2. Frontend generates UUID: "3d02d801-..."
3. Frontend adds to state with that ID
4. Backend receives message, creates HumanMessage with different ID: "b0cfa23b-..."
5. Frontend tries to regenerate using "3d02d801-..." ❌ Backend doesn't know this ID
```

### Fixed Flow (With Sync)
```
1. User types message
2. Frontend adds with temp ID: "temp-abc123..."
3. Backend receives message, creates HumanMessage with ID: "b0cfa23b-..."
4. Backend emits user_message_confirmed event with ID "b0cfa23b-..."
5. Frontend updates temp message with backend ID
6. Frontend can now regenerate using "b0cfa23b-..." ✅ Backend knows this ID
```

## Testing

After implementing the frontend changes, verify:

1. **Message ID Sync**: Check browser console that `user_message_confirmed` events are received
2. **State Update**: Verify message IDs in your state match backend IDs
3. **Regenerate Endpoint**: Test regenerating from a specific message - should work now
4. **Message History**: Reload page and verify messages still have correct IDs

## Backend Event Example

The backend now emits this event:
```json
{
  "type": "user_message_confirmed",
  "message_id": "b0cfa23b-7461-4c8f-a832-a8ae2b045616",
  "content": "What is the Open Bank Project?",
  "timestamp": 1730649872.123
}
```

## Type Definitions

Add to your frontend types:

```typescript
interface UserMessageConfirmedEvent {
    type: 'user_message_confirmed';
    messageId: string;
    content: string;
    timestamp: number;
}

// Update StreamEvent union
type StreamEvent = 
    | AssistantStartEvent
    | AssistantTokenEvent
    | UserMessageConfirmedEvent  // Add this
    | ToolStartEvent
    | ...
```
