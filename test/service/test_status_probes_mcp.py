"""The MCP part of /status: servers that need the user's token are not test-called without one (no noisy warning)."""
import asyncio

from agent.components.tools.mcp_integration import MCPServerConfig
from service import status_probes


class _MustNotConnect:
    def __init__(self, *args, **kwargs):
        raise AssertionError("the status check must not connect to a server that needs the user's token")


def test_a_server_needing_the_users_token_is_skipped(monkeypatch):
    server = MCPServerConfig(name="obp-mcp", url="http://localhost:9100/mcp", forward_bearer_token=True)
    monkeypatch.setattr(status_probes, "get_server_configs", lambda: [server])
    monkeypatch.setattr(status_probes, "get_mcp_tools", lambda: [])
    monkeypatch.setattr(status_probes, "_obp_mcp_status_url", lambda: None)
    monkeypatch.setattr(status_probes, "MCPToolLoader", _MustNotConnect)

    result = asyncio.run(status_probes._probe_mcp())

    assert result["test_call"] == "skipped: needs a user's token"
    assert result["up"] is True
