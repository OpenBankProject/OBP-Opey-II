# Client-executed tools

A client-executed tool runs in the USER'S BROWSER, not in this service. The
canonical example is `set_form_fields`: Opey drafts values into a form the
user has open; the user reviews and submits themselves.

## Contract

- **Opt-in per request**: `StreamInput.client_tools: ["set_form_fields", ...]`.
  Only declared tools are registered into the graph
  (`OpeySession.async_init` → `agent/components/tools/client_tools.py`).
  Clients must re-send the declaration on EVERY /stream request of the
  conversation — the graph is rebuilt per request, and the resumed tool batch
  re-executes inside it.
- **Page context**: `StreamInput.client_context` (free text: form name, field
  names/types, current values) is injected as an ephemeral SystemMessage each
  turn (like `current_bank_id`), never persisted.
- **The pause**: the tool body is a single `interrupt()` carrying
  `{"client_tool", "tool_call_id", "tool_input"}`. After the stream drains,
  `StreamManager._handle_approval` emits SSE `client_tool_call`
  `{tool_call_id, tool_name, tool_input}`.
- **The resume**: `POST /stream` with
  `tool_call_approval.client_tool_result = {tool_call_id, status, result}`
  (`status`: applied | rejected | error) → `Command(resume=...)`; the tool
  returns the dict JSON-encoded as its ToolMessage content.
- **Abandoned interrupts** (page closed, new user message first) are resolved
  as cancelled by `_fix_pending_interrupts` with an error ToolMessage.

## Cautions

- `interrupt()` inside ToolNode re-executes the WHOLE tool batch on resume —
  every client tool's docstring must demand "call this tool on its own". If a
  model ever pairs one with a mutating MCP call, move that tool to a
  dedicated node modelled on `consent_check_node`.
- Client tools are safe in every OBP_API_MODE: they touch page state in the
  user's browser only, never OBP.

Tests: `test/agent/test_client_tools.py`. Frontend counterpart:
OBP-Frontend `packages/shared/src/lib/opey/` and
`apps/api-manager/docs/OPEY_FORM_FILL.md`.
