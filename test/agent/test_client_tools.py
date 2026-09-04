"""
Tests for client-executed tools (set_form_fields) and their interrupt round trip.

The contract under test:
- make_client_tools registers only known, declared tools
- ToolCallApproval.client_tool_result is recognised and routed
- a client tool inside ToolNode pauses the graph with a client_tool payload and,
  on Command(resume=...), returns the client's result as the ToolMessage content
- the SSE event for the browser has the right shape
"""
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from agent.components.tools.client_tools import CLIENT_TOOLS, make_client_tools, set_form_fields
from schema.schema import ClientToolResult, StreamInput, ToolCallApproval
from service.streaming.events import StreamEventFactory


def test_make_client_tools_filters_unknown_names():
    tools = make_client_tools(["set_form_fields", "made_up_tool"])
    assert [t.name for t in tools] == ["set_form_fields"]
    assert make_client_tools([]) == []
    assert make_client_tools(None) == []


def test_registry_contains_set_form_fields():
    assert "set_form_fields" in CLIENT_TOOLS
    assert CLIENT_TOOLS["set_form_fields"].name == "set_form_fields"


def test_llm_facing_schema_hides_injected_tool_call_id():
    # tool_call_schema is what bind_tools sends to the model; the injected
    # tool_call_id must not appear there (ToolNode injects it at execution).
    schema = set_form_fields.tool_call_schema.model_json_schema()
    assert "fields" in schema["properties"]
    assert "note" in schema["properties"]
    assert "tool_call_id" not in schema["properties"]


def test_tool_call_approval_recognises_client_tool_result():
    approval = ToolCallApproval(
        client_tool_result=ClientToolResult(
            tool_call_id="call_1", status="applied", result={"applied": ["summary"]}
        )
    )
    assert approval.is_client_tool_result()
    assert not approval.is_consent_response()
    assert not approval.is_batch()
    # Nested tool_call_id must not trip the legacy single-approval path
    assert not approval.is_single()

    assert not ToolCallApproval(approval="approve", tool_call_id="x").is_client_tool_result()


def test_stream_input_declares_client_tools_and_context():
    si = StreamInput(message="hi")
    assert si.client_tools == []
    assert si.client_context is None

    si = StreamInput(message="hi", client_tools=["set_form_fields"], client_context="form: ...")
    assert si.client_tools == ["set_form_fields"]


def test_client_tool_call_event_shape():
    event = StreamEventFactory.client_tool_call(
        tool_call_id="call_1",
        tool_name="set_form_fields",
        tool_input={"fields": {"summary": "Get branches"}, "note": ""},
    )
    data = json.loads(event.to_sse_data()[len("data: "):])
    assert data["type"] == "client_tool_call"
    assert data["tool_call_id"] == "call_1"
    assert data["tool_name"] == "set_form_fields"
    assert data["tool_input"]["fields"] == {"summary": "Get branches"}


def _tool_only_graph():
    """Minimal graph: START -> tools -> END, checkpointed so interrupt() works."""
    workflow = StateGraph(MessagesState)
    workflow.add_node("tools", ToolNode([set_form_fields]))
    workflow.add_edge(START, "tools")
    workflow.add_edge("tools", END)
    return workflow.compile(checkpointer=MemorySaver())


@pytest.mark.asyncio
async def test_interrupt_round_trip_returns_client_result_as_tool_message():
    graph = _tool_only_graph()
    config = {"configurable": {"thread_id": "t1"}}

    ai = AIMessage(
        content="",
        tool_calls=[{
            "id": "call_1",
            "name": "set_form_fields",
            "args": {"fields": {"summary": "Get branches"}, "note": "draft"},
        }],
    )

    # First run pauses on the interrupt inside the tool
    await graph.ainvoke({"messages": [ai]}, config)
    state = await graph.aget_state(config)
    interrupts = [i for task in state.tasks for i in task.interrupts]
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["client_tool"] == "set_form_fields"
    assert payload["tool_call_id"] == "call_1"
    assert payload["tool_input"] == {"fields": {"summary": "Get branches"}, "note": "draft"}

    # Resume with the client's result — exactly what stream_manager sends
    client_result = ClientToolResult(
        tool_call_id="call_1", status="applied", result={"applied": ["summary"], "ignored": []}
    )
    await graph.ainvoke(Command(resume=client_result.model_dump()), config)

    state = await graph.aget_state(config)
    assert not [i for task in state.tasks for i in task.interrupts]
    tool_messages = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    content = json.loads(tool_messages[0].content)
    assert content["status"] == "applied"
    assert content["result"]["applied"] == ["summary"]
