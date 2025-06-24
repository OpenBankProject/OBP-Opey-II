"""
Frontend Integration Demo for Simplified Streaming System

This demo shows how the simplified streaming approach makes frontend integration
much easier by leveraging LangGraph's built-in node metadata.
"""

import asyncio
import json
from typing import Dict, Any, List
from dataclasses import dataclass

# Simulate the simplified events (without importing the full system)
@dataclass
class StreamEvent:
    type: str
    data: Dict[str, Any]
    node_name: str = ""
    run_id: str = ""

class FrontendStreamHandler:
    """
    Demonstrates how a frontend application would handle the simplified stream events.

    With the simplified approach, the frontend just needs to check:
    1. The event type (assistant_token, tool_start, etc.)
    2. The node name from metadata (opey, tools, human_review, etc.)

    This makes it trivial to show the right UI elements.
    """

    def __init__(self):
        self.current_response = ""
        self.active_tools = {}
        self.ui_state = {
            "assistant_typing": False,
            "tools_running": [],
            "approval_pending": None,
            "search_active": False
        }

    def handle_stream_event(self, event: StreamEvent):
        """Handle a stream event and update UI state accordingly."""

        print(f"\n📨 Event: {event.type} (from node: {event.node_name})")

        # Route based on event type
        match event.type:
            case "assistant_start":
                self.handle_assistant_start(event)
            case "assistant_token":
                self.handle_assistant_token(event)
            case "assistant_complete":
                self.handle_assistant_complete(event)
            case "tool_start":
                self.handle_tool_start(event)
            case "tool_end":
                self.handle_tool_end(event)
            case "approval_request":
                self.handle_approval_request(event)
            case "error":
                self.handle_error(event)
            case "stream_end":
                self.handle_stream_end(event)

    def handle_assistant_start(self, event: StreamEvent):
        """Show typing indicator for assistant."""
        self.ui_state["assistant_typing"] = True
        self.current_response = ""
        print("  🤖 UI: Show typing indicator")
        print("  💭 Assistant is thinking...")

    def handle_assistant_token(self, event: StreamEvent):
        """Display streaming tokens from assistant."""
        token = event.data.get("content", "")
        self.current_response += token
        print(f"  💬 UI: Append token '{token}' to response")
        print(f"      Current response: '{self.current_response}'")

    def handle_assistant_complete(self, event: StreamEvent):
        """Complete assistant response and show any tool calls."""
        self.ui_state["assistant_typing"] = False
        content = event.data.get("content", "")
        tool_calls = event.data.get("tool_calls", [])

        print("  ✅ UI: Hide typing indicator")
        print(f"  📝 Final response: '{content}'")

        if tool_calls:
            print(f"  🔧 UI: Show {len(tool_calls)} tool call preview(s)")
            for tool_call in tool_calls:
                print(f"      - {tool_call.get('name', 'unknown')}: {tool_call.get('args', {})}")

    def handle_tool_start(self, event: StreamEvent):
        """Show tool execution UI based on node type."""
        tool_name = event.data.get("tool_name", "")
        tool_call_id = event.data.get("tool_call_id", "")
        tool_input = event.data.get("tool_input", {})

        self.active_tools[tool_call_id] = {
            "name": tool_name,
            "node": event.node_name,
            "status": "running"
        }

        # Different UI based on what type of tool/node
        ui_info = self.get_node_ui_info(event.node_name)

        print(f"  🔧 UI: Start {ui_info['type']} indicator")
        print(f"      Tool: {tool_name}")
        print(f"      Input: {tool_input}")
        print(f"      UI Elements: {ui_info['ui_elements']}")

        # Update UI state
        if event.node_name in ["retrieve_endpoints", "retrieve_glossary"]:
            self.ui_state["search_active"] = True
            print("  🔍 UI: Show search indicator")
        else:
            self.ui_state["tools_running"].append(tool_call_id)
            print("  ⚙️ UI: Show tool execution spinner")

    def handle_tool_end(self, event: StreamEvent):
        """Complete tool execution and show results."""
        tool_call_id = event.data.get("tool_call_id", "")
        tool_output = event.data.get("tool_output", {})
        status = event.data.get("status", "success")

        if tool_call_id in self.active_tools:
            tool_info = self.active_tools[tool_call_id]
            tool_info["status"] = status

            print(f"  ✅ UI: Complete {tool_info['name']} ({status})")
            print(f"      Output: {tool_output}")

            # Update UI based on node type
            if tool_info["node"] in ["retrieve_endpoints", "retrieve_glossary"]:
                self.ui_state["search_active"] = False
                print("  🔍 UI: Hide search indicator, show results")

                # Show search results in a nice format
                if isinstance(tool_output, dict) and "endpoints" in tool_output:
                    endpoints = tool_output["endpoints"]
                    print(f"      📋 Found {len(endpoints)} endpoint(s)")
                    for endpoint in endpoints[:3]:  # Show first 3
                        print(f"         - {endpoint}")
            else:
                if tool_call_id in self.ui_state["tools_running"]:
                    self.ui_state["tools_running"].remove(tool_call_id)
                print("  ⚙️ UI: Hide tool spinner, show results")

    def handle_approval_request(self, event: StreamEvent):
        """Show approval modal for dangerous operations."""
        tool_name = event.data.get("tool_name", "")
        tool_input = event.data.get("tool_input", {})
        message = event.data.get("message", "")

        self.ui_state["approval_pending"] = event.data

        print("  ⚠️ UI: Show approval modal")
        print(f"      Tool: {tool_name}")
        print(f"      Operation: {tool_input.get('method', '')} {tool_input.get('path', '')}")
        print(f"      Message: {message}")
        print("      🟢 [Approve Button] 🔴 [Deny Button]")

    def handle_error(self, event: StreamEvent):
        """Show error message."""
        error_message = event.data.get("error_message", "")
        error_code = event.data.get("error_code", "")

        print("  ❌ UI: Show error notification")
        print(f"      Message: {error_message}")
        if error_code:
            print(f"      Code: {error_code}")

    def handle_stream_end(self, event: StreamEvent):
        """Clean up UI state."""
        print("  🏁 UI: Stream ended, cleanup UI state")
        self.ui_state = {
            "assistant_typing": False,
            "tools_running": [],
            "approval_pending": None,
            "search_active": False
        }

    def get_node_ui_info(self, node_name: str) -> Dict[str, Any]:
        """Get UI information for a node - this would be a lookup table."""
        node_ui_mapping = {
            "opey": {
                "type": "assistant",
                "ui_elements": ["typing_indicator", "message_bubble"]
            },
            "tools": {
                "type": "tool_execution",
                "ui_elements": ["spinner", "progress_bar"]
            },
            "retrieve_endpoints": {
                "type": "search",
                "ui_elements": ["search_indicator", "results_list"]
            },
            "retrieve_glossary": {
                "type": "search",
                "ui_elements": ["search_indicator", "glossary_results"]
            },
            "human_review": {
                "type": "approval",
                "ui_elements": ["approval_modal", "buttons"]
            }
        }
        return node_ui_mapping.get(node_name, {"type": "unknown", "ui_elements": ["generic"]})

async def simulate_conversation_flow():
    """Simulate a complete conversation flow to show frontend integration."""

    print("🚀 Simulating OBP-Opey Conversation Flow")
    print("=" * 60)

    handler = FrontendStreamHandler()

    # Simulate a conversation: "What endpoints are available for accounts?"
    conversation_events = [
        # Assistant starts responding
        StreamEvent("assistant_start", {"run_id": "demo-123"}, "opey"),

        # Assistant streams response
        StreamEvent("assistant_token", {"content": "I'll", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " help", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " you", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " find", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " account", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " endpoints.", "run_id": "demo-123"}, "opey"),

        # Assistant completes with tool call
        StreamEvent("assistant_complete", {
            "content": "I'll help you find account endpoints.",
            "tool_calls": [{"name": "retrieve_endpoints", "id": "call_123", "args": {"query": "account endpoints"}}],
            "run_id": "demo-123"
        }, "opey"),

        # Tool starts (endpoint search)
        StreamEvent("tool_start", {
            "tool_name": "retrieve_endpoints",
            "tool_call_id": "call_123",
            "tool_input": {"query": "account endpoints"},
            "run_id": "demo-123"
        }, "retrieve_endpoints"),

        # Tool completes
        StreamEvent("tool_end", {
            "tool_name": "retrieve_endpoints",
            "tool_call_id": "call_123",
            "tool_output": {
                "endpoints": [
                    "/obp/v5.0.0/banks/BANK_ID/accounts",
                    "/obp/v5.0.0/banks/BANK_ID/accounts/ACCOUNT_ID",
                    "/obp/v5.0.0/banks/BANK_ID/accounts/ACCOUNT_ID/transactions"
                ]
            },
            "status": "success",
            "run_id": "demo-123"
        }, "retrieve_endpoints"),

        # Assistant continues with more response
        StreamEvent("assistant_start", {"run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " Here", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " are", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " the", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " account", "run_id": "demo-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " endpoints!", "run_id": "demo-123"}, "opey"),

        StreamEvent("assistant_complete", {
            "content": " Here are the account endpoints!",
            "tool_calls": [],
            "run_id": "demo-123"
        }, "opey"),

        StreamEvent("stream_end", {}, "")
    ]

    # Process each event with a small delay to simulate real streaming
    for event in conversation_events:
        handler.handle_stream_event(event)
        await asyncio.sleep(0.3)  # Simulate streaming delay

    print(f"\n📊 Final UI State: {handler.ui_state}")

async def simulate_approval_flow():
    """Simulate a flow that requires approval."""

    print("\n\n🔐 Simulating Approval Flow")
    print("=" * 60)

    handler = FrontendStreamHandler()

    # Simulate: "Create a new bank account"
    approval_events = [
        StreamEvent("assistant_start", {"run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": "I'll", "run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " create", "run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " a", "run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " bank", "run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " account.", "run_id": "approval-123"}, "opey"),

        StreamEvent("assistant_complete", {
            "content": "I'll create a bank account.",
            "tool_calls": [{"name": "obp_requests", "id": "dangerous_call", "args": {"method": "POST", "path": "/accounts"}}],
            "run_id": "approval-123"
        }, "opey"),

        # This triggers approval request
        StreamEvent("approval_request", {
            "tool_name": "obp_requests",
            "tool_call_id": "dangerous_call",
            "tool_input": {"method": "POST", "path": "/obp/v5.0.0/banks/gh.29.uk/accounts"},
            "message": "This will create a new bank account. Proceed?",
            "run_id": "approval-123"
        }, "human_review"),

        # Simulate user approval (this would come from UI interaction)
        StreamEvent("tool_start", {
            "tool_name": "obp_requests",
            "tool_call_id": "dangerous_call",
            "tool_input": {"method": "POST", "path": "/accounts"},
            "run_id": "approval-123"
        }, "tools"),

        StreamEvent("tool_end", {
            "tool_name": "obp_requests",
            "tool_call_id": "dangerous_call",
            "tool_output": {"account_id": "new_account_456", "status": "created"},
            "status": "success",
            "run_id": "approval-123"
        }, "tools"),

        StreamEvent("assistant_start", {"run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " Account", "run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " created", "run_id": "approval-123"}, "opey"),
        StreamEvent("assistant_token", {"content": " successfully!", "run_id": "approval-123"}, "opey"),

        StreamEvent("assistant_complete", {
            "content": " Account created successfully!",
            "tool_calls": [],
            "run_id": "approval-123"
        }, "opey"),

        StreamEvent("stream_end", {}, "")
    ]

    for event in approval_events:
        handler.handle_stream_event(event)
        await asyncio.sleep(0.3)

def demonstrate_frontend_code():
    """Show example frontend code that would handle these events."""

    print("\n\n💻 Example Frontend Implementation")
    print("=" * 60)

    frontend_code = '''
// React/TypeScript example for handling simplified streaming events

interface StreamEvent {
  type: string;
  data: any;
  node_name?: string;
  run_id?: string;
}

const StreamingChat: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [uiState, setUiState] = useState({
    assistantTyping: false,
    toolsRunning: [],
    approvalPending: null,
    searchActive: false
  });

  const handleStreamEvent = (event: StreamEvent) => {
    switch (event.type) {
      case 'assistant_start':
        setUiState(prev => ({ ...prev, assistantTyping: true }));
        break;

      case 'assistant_token':
        // Append token to current message
        updateCurrentMessage(event.data.content);
        break;

      case 'assistant_complete':
        setUiState(prev => ({ ...prev, assistantTyping: false }));
        finalizeMessage(event.data.content);
        break;

      case 'tool_start':
        // Show different UI based on node_name
        if (event.node_name === 'retrieve_endpoints') {
          setUiState(prev => ({ ...prev, searchActive: true }));
          showSearchIndicator();
        } else {
          showToolSpinner(event.data.tool_call_id);
        }
        break;

      case 'tool_end':
        if (event.node_name === 'retrieve_endpoints') {
          setUiState(prev => ({ ...prev, searchActive: false }));
          showSearchResults(event.data.tool_output);
        } else {
          hideToolSpinner(event.data.tool_call_id);
        }
        break;

      case 'approval_request':
        setUiState(prev => ({
          ...prev,
          approvalPending: event.data
        }));
        showApprovalModal(event.data);
        break;
    }
  };

  return (
    <div className="streaming-chat">
      {/* Chat messages */}
      <MessageList messages={messages} />

      {/* Typing indicator */}
      {uiState.assistantTyping && <TypingIndicator />}

      {/* Search indicator */}
      {uiState.searchActive && <SearchIndicator />}

      {/* Tool spinners */}
      {uiState.toolsRunning.map(toolId =>
        <ToolSpinner key={toolId} toolId={toolId} />
      )}

      {/* Approval modal */}
      {uiState.approvalPending && (
        <ApprovalModal
          request={uiState.approvalPending}
          onApprove={() => handleApproval(true)}
          onDeny={() => handleApproval(false)}
        />
      )}
    </div>
  );
};
'''

    print(frontend_code)

async def main():
    """Run all demonstrations."""
    try:
        await simulate_conversation_flow()
        await simulate_approval_flow()
        demonstrate_frontend_code()

        print("\n\n🎉 Key Benefits of Simplified Approach:")
        print("✅ Frontend only needs to check event.type and event.node_name")
        print("✅ No complex logic - LangGraph metadata tells us everything")
        print("✅ Easy to add new node types and UI behaviors")
        print("✅ Clear separation between backend streaming and frontend UI")
        print("✅ Each node type maps directly to specific UI elements")
        print("✅ Approval flows are naturally handled by node transitions")

    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
