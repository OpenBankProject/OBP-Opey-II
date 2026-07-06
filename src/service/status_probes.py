"""Public /status endpoint helpers: dependency probes with TTL cache + single-flight lock."""
import asyncio
import html
import logging
import os
import time
import tomllib
from pathlib import Path
from typing import Any

import aiohttp
from urllib.parse import urlsplit, urlunsplit

from agent.components.tools import MCPToolLoader

from .checkpointer import checkpointers
from .mcp_tools_cache import get_mcp_tools, get_server_configs
from .redis_client import get_redis_client

logger = logging.getLogger("opey.service.status")

_PROBE_TIMEOUT_SEC = 2.0
_MCP_TEST_CALL_TIMEOUT_SEC = 5.0  # full MCP handshake + tools/list is heavier than an HTTP ping
_CACHE_TTL_SEC = 15.0

_start_time_monotonic = time.monotonic()

_cache: dict[str, Any] | None = None
_cache_expires: float = 0.0
_lock = asyncio.Lock()


async def _probe_obp() -> dict[str, Any]:
    base = os.getenv("OBP_BASE_URL")
    if not base:
        return {"up": False, "latency_ms": None}
    url = f"{base.rstrip('/')}/obp/v5.1.0/root"
    start = time.monotonic()
    up = False
    try:
        timeout = aiohttp.ClientTimeout(total=_PROBE_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                up = resp.status < 500
    except Exception:
        up = False
    return {"up": up, "latency_ms": int((time.monotonic() - start) * 1000)}


async def _probe_redis() -> dict[str, Any]:
    start = time.monotonic()
    up = False
    try:
        client = get_redis_client()
        up = bool(await asyncio.wait_for(client.ping(), timeout=_PROBE_TIMEOUT_SEC))
    except Exception:
        up = False
    return {"up": up, "latency_ms": int((time.monotonic() - start) * 1000)}


async def _probe_checkpointer() -> dict[str, Any]:
    # AsyncSqliteSaver is populated during app lifespan startup; presence is a sufficient probe.
    return {"up": "aiosql" in checkpointers and checkpointers["aiosql"] is not None}


_OBP_MCP_SERVER_NAMES = ("obp", "obp-mcp")


def _obp_mcp_status_url() -> str | None:
    """Derive the OBP-MCP /status URL from its configured MCP endpoint URL."""
    for cfg in get_server_configs():
        if cfg.name in _OBP_MCP_SERVER_NAMES and cfg.url:
            parts = urlsplit(cfg.url)
            if not parts.scheme or not parts.netloc:
                return None
            netloc = parts.netloc
            # 0.0.0.0 is a bind-any address, not a valid connect target — map to loopback.
            if parts.hostname == "0.0.0.0":
                netloc = netloc.replace("0.0.0.0", "127.0.0.1", 1)
            return urlunsplit((parts.scheme, netloc, "/status", "format=json", ""))
    return None


async def _probe_mcp() -> dict[str, Any]:
    # No MCP servers configured means the agent has no OBP tools at all (e.g.
    # mcp_servers.json missing from the deployment) — surface that as down
    # rather than a green "up · 0 tools".
    configs = get_server_configs()
    if not configs:
        return {"up": False, "tool_count": 0, "detail": "no MCP servers configured"}

    try:
        tools = get_mcp_tools()
        result: dict[str, Any] = {"up": True, "tool_count": len(tools)}
    except Exception:
        result = {"up": False, "tool_count": 0}

    # Auth-required OBP-MCP servers are never connected at startup (tools are
    # loaded per-request with the user's bearer token), so the tools cache says
    # nothing about reachability. When an OBP-MCP server is configured, probe
    # its /status endpoint directly: reachability drives "up", and the outbound
    # auth mode is included when the response parses.
    url = _obp_mcp_status_url()
    if url:
        start = time.monotonic()
        reachable = False
        try:
            timeout = aiohttp.ClientTimeout(total=_PROBE_TIMEOUT_SEC)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"Accept": "application/json"}) as resp:
                    reachable = resp.status < 500
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            mode = (data.get("auth") or {}).get("outbound_auth_via")
                            if mode:
                                result["obp_mcp_outbound_auth_via"] = mode
                        except Exception:
                            pass  # auth mode is informational only
        except Exception:
            reachable = False
        result["up"] = reachable
        result["latency_ms"] = int((time.monotonic() - start) * 1000)

    # Protocol-level test call: perform a real MCP handshake + tools/list over the
    # same loader the agent uses. MCPToolLoader is used directly (not the
    # create_mcp_tools_with_auth wrapper, which swallows connection errors into an
    # empty list). Unauthenticated — succeeds when the server's inbound auth is
    # disabled (e.g. consent-based OBP-MCP setups); with inbound auth enabled it
    # may fail, so a failure is reported but does not demote "up".
    if configs:
        try:
            loader = MCPToolLoader(servers=configs)
            tools = await asyncio.wait_for(
                loader.load_tools(), timeout=_MCP_TEST_CALL_TIMEOUT_SEC
            )
            result["test_call"] = "ok"
            result["tool_count"] = len(tools)
        except Exception as e:
            logger.warning(f"MCP test call failed: {type(e).__name__}: {e}")
            result["test_call"] = "failed"

    return result


async def _probe_llm() -> dict[str, Any]:
    # Don't call the provider — just verify credentials are configured.
    # Calling would cost money and let a public endpoint amplify traffic to an LLM API.
    configured = any(os.getenv(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
    return {"up": configured}


def _get_version() -> str:
    try:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data.get("tool", {}).get("poetry", {}).get("version") or "unknown"
    except Exception:
        return "unknown"


async def _compute_status() -> dict[str, Any]:
    obp, redis_r, ck, mcp, llm = await asyncio.gather(
        _probe_obp(),
        _probe_redis(),
        _probe_checkpointer(),
        _probe_mcp(),
        _probe_llm(),
    )
    components = {
        "obp": obp,
        "redis": redis_r,
        "checkpointer": ck,
        "mcp": mcp,
        "llm": llm,
    }
    overall = "ok" if all(c.get("up") for c in components.values()) else "degraded"
    return {
        "overall": overall,
        "version": _get_version(),
        "uptime_seconds": int(time.monotonic() - _start_time_monotonic),
        "components": components,
    }


async def get_cached_status() -> dict[str, Any]:
    """Return cached status if fresh; otherwise probe dependencies under a single-flight lock."""
    global _cache, _cache_expires
    if _cache is not None and time.monotonic() < _cache_expires:
        return _cache
    async with _lock:
        if _cache is not None and time.monotonic() < _cache_expires:
            return _cache
        _cache = await _compute_status()
        _cache_expires = time.monotonic() + _CACHE_TTL_SEC
        return _cache


def render_status_html(status: dict[str, Any]) -> str:
    """Render the status payload as a small self-contained HTML page. Escapes all dynamic values."""
    overall = status.get("overall", "unknown")
    overall_class = "ok" if overall == "ok" else "degraded"
    version = html.escape(str(status.get("version", "unknown")))
    uptime = int(status.get("uptime_seconds", 0))

    rows = []
    for name, data in status.get("components", {}).items():
        up = bool(data.get("up"))
        dot = "ok" if up else "down"
        label = "up" if up else "down"
        extras = []
        if "latency_ms" in data and data["latency_ms"] is not None:
            extras.append(f"{int(data['latency_ms'])} ms")
        if "tool_count" in data:
            extras.append(f"{int(data['tool_count'])} tools")
        if "test_call" in data:
            extras.append(f"test call: {data['test_call']}")
        if "obp_mcp_outbound_auth_via" in data:
            extras.append(f"OBP-MCP auth: {data['obp_mcp_outbound_auth_via']}")
        if "detail" in data:
            extras.append(str(data["detail"]))
        extra_text = html.escape(" · ".join(extras)) if extras else ""
        rows.append(
            f'<tr><td><span class="dot {dot}"></span>{html.escape(name)}</td>'
            f'<td>{label}</td><td class="muted">{extra_text}</td></tr>'
        )
    rows_html = "\n".join(rows)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Opey status</title>
<meta name="robots" content="noindex">
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1 {{ margin-bottom: 0.25rem; }}
  .overall {{ display: inline-block; padding: 0.25rem 0.6rem; border-radius: 4px; font-weight: 600; }}
  .overall.ok {{ background: #e6f4ea; color: #137333; }}
  .overall.degraded {{ background: #fce8e6; color: #b3261e; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1.5rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.25rem; border-bottom: 1px solid #eee; }}
  th {{ font-size: 0.85rem; text-transform: uppercase; color: #666; }}
  .dot {{ display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%; margin-right: 0.5rem; vertical-align: middle; }}
  .dot.ok {{ background: #137333; }}
  .dot.down {{ background: #b3261e; }}
  .muted {{ color: #666; font-size: 0.9rem; }}
  footer {{ margin-top: 2rem; font-size: 0.85rem; color: #666; }}
</style>
</head>
<body>
  <h1>Opey status</h1>
  <p><span class="overall {overall_class}">{html.escape(overall)}</span></p>
  <table>
    <thead><tr><th>Component</th><th>State</th><th></th></tr></thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
  <footer>version {version} · uptime {uptime}s · cached up to {int(_CACHE_TTL_SEC)}s</footer>
</body>
</html>
"""
