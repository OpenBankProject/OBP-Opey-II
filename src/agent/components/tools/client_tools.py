"""
Client-executed tools.

These tools run in the BROWSER, not on the server: the tool body is a single
LangGraph `interrupt()`. The stream manager turns the interrupt into a
`client_tool_call` SSE event; the frontend executes the action (e.g. writes
values into a form), then resumes via POST /stream with
`tool_call_approval.client_tool_result`, whose payload `interrupt()` returns
here and becomes the ToolMessage content the model sees.

Registration is opt-in per request: a tool is only added to the graph when the
client declared its name in `StreamInput.client_tools` (see
`OpeySession.async_init`). A client that never declares a tool can never
receive a `client_tool_call` event, so old clients cannot hang.

Contract notes for tool authors:
- Because `interrupt()` fires inside ToolNode, the WHOLE tool batch of the
  interrupted super-step re-executes on resume. The docstring of every client
  tool therefore instructs the model to call it alone; keep it that way.
- Client tools must be page-agnostic. What the page can do (e.g. which form
  fields exist) arrives via `StreamInput.client_context`; the browser ignores
  unknown keys and echoes them back as `ignored`, which is the model's
  corrective loop.
"""
import json
import logging
from typing import Annotated, Any

from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import interrupt

logger = logging.getLogger(__name__)


@tool
async def set_form_fields(
    fields: dict[str, Any] | None = None,
    note: str = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> str:
    """Fill fields of the form the user currently has open in their browser.

    Use the exact field names, types and current values given in the page
    context of this conversation; keys the page does not know are ignored.
    Only include the fields you want to change — existing values of other
    fields are kept. The user sees every change highlighted and can revert it;
    nothing is submitted.

    IMPORTANT: call this tool ON ITS OWN, never in the same round as other
    tool calls.

    Args:
        fields: Mapping of form field name to new value.
        note: Optional one-line summary of what you filled and why.
    """
    if not fields:
        # The arguments arrived empty. The usual cause is the reply being cut off by the output
        # token limit while a long value was being written, which leaves the call with no
        # arguments at all. Tell the model instead of raising, so it can recover in the next turn
        # rather than the user seeing a validation trace.
        logger.warning("set_form_fields called with no fields (tool_call_id=%s)", tool_call_id)
        return json.dumps({
            "tool_call_id": tool_call_id,
            "status": "error",
            "error": (
                "No `fields` were received: the tool call arguments were empty. This happens when the "
                "reply was cut off before the arguments were complete. Call set_form_fields again with "
                "the complete `fields` object. If a value is very long, send it on its own in one call."
            ),
        })
    result = interrupt({
        "client_tool": "set_form_fields",
        "tool_call_id": tool_call_id,
        "tool_input": {"fields": fields, "note": note},
    })
    # `result` is ClientToolResult.model_dump() from the resume request:
    # {"tool_call_id": ..., "status": "applied"|"rejected"|"error", "result": {...}}
    return json.dumps(result)


# Registry of every client tool the service knows how to offer.
CLIENT_TOOLS: dict[str, BaseTool] = {
    "set_form_fields": set_form_fields,
}


def make_client_tools(names: list[str]) -> list[BaseTool]:
    """The client tools a request declared support for; unknown names are logged and dropped."""
    tools: list[BaseTool] = []
    for name in names or []:
        t = CLIENT_TOOLS.get(name)
        if t is not None:
            tools.append(t)
        else:
            logger.warning(f"Client declared unknown client tool '{name}' — ignoring")
    return tools
