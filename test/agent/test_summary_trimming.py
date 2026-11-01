"""Summarizing a long conversation trims it with a local token estimate: no provider call per candidate cut (Anthropic
answers 400 to counting a cut that starts with a tool_result), and each kept tool_result keeps its tool_use."""
import asyncio

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

from agent.components import nodes


class _Summary:
    content = "The user asked for the current user; Opey called the API."


def test_a_long_tool_result_is_summarized_without_calling_the_provider(monkeypatch):
    class _Chain:
        async def ainvoke(self, _input):
            return _Summary()

    monkeypatch.setattr(nodes, "conversation_summarizer_chain", _Chain())
    big = '{"entitlements": [' + ",".join(['{"role_name": "CanGetSomething"}'] * 3000) + "]}"
    messages = [
        HumanMessage(content="can you get the current user", id="h1"),
        AIMessage(content="", id="a1", tool_calls=[{"name": "call_obp_api", "args": {}, "id": "toolu_1"}]),
        ToolMessage(content=big, tool_call_id="toolu_1", id="t1"),
        AIMessage(content="Here is the current user.", id="a2"),
        HumanMessage(content="thanks", id="h2"),
    ]

    result = asyncio.run(nodes.run_summary_chain({"messages": messages, "total_tokens": 60000}))

    removed = {m.id for m in result["messages"] if isinstance(m, RemoveMessage)}
    kept = [m for m in messages if m.id not in removed]
    kept_tool_results = {m.tool_call_id for m in kept if isinstance(m, ToolMessage)}
    kept_tool_calls = {c["id"] for m in kept if isinstance(m, AIMessage) for c in (m.tool_calls or [])}
    assert kept, "the conversation must not be emptied"
    assert kept_tool_results <= kept_tool_calls, "every kept tool_result needs its tool_use"
