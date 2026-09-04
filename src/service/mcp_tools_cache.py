"""
Application-level MCP tools cache.

Loads MCP server configurations at startup. Tools can be loaded:
1. At startup (for servers that don't require auth)
2. Per-request with bearer token (for servers requiring user authentication)
"""
import os
import json
import logging
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

from langchain_core.tools import BaseTool
from agent.components.tools import MCPToolLoader, MCPServerConfig, MCPConnectionError, create_mcp_tools_with_auth
from auth.service_token import service_token_provider

logger = logging.getLogger(__name__)

# Module-level cache
_mcp_tools: Optional[List[BaseTool]] = None
_mcp_loader: Optional[MCPToolLoader] = None
_server_configs: Optional[List[MCPServerConfig]] = None

# Default config file path (relative to project root)
DEFAULT_MCP_CONFIG_FILE = "mcp_servers.json"


def _find_config_file() -> Optional[Path]:
    """
    Find the MCP servers config file.
    
    Checks in order:
    1. Path specified in MCP_SERVERS_FILE environment variable
    2. mcp_servers.json in current working directory
    3. mcp_servers.json in src/ directory
    """
    # Check environment variable first
    env_path = os.getenv("MCP_SERVERS_FILE")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
        logger.warning(f"MCP_SERVERS_FILE set to {env_path} but file not found")
    
    # Check current directory
    cwd_path = Path.cwd() / DEFAULT_MCP_CONFIG_FILE
    if cwd_path.exists():
        return cwd_path
    
    # Check src directory (for when running from project root)
    src_path = Path.cwd() / "src" / DEFAULT_MCP_CONFIG_FILE
    if src_path.exists():
        return src_path
    
    return None


def _parse_mcp_config() -> List[MCPServerConfig]:
    """Parse MCP servers config file into config objects."""
    config_file = _find_config_file()
    
    if not config_file:
        logger.info(f"No MCP config file found (checked {DEFAULT_MCP_CONFIG_FILE})")
        return []
    
    logger.info(f"Loading MCP config from {config_file}")
    
    try:
        with open(config_file) as f:
            config_data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {config_file}: {e}")
        return []
    except IOError as e:
        logger.error(f"Failed to read {config_file}: {e}")
        return []
    
    # Support both {"servers": [...]} and [...] formats
    if isinstance(config_data, dict):
        server_configs_raw = config_data.get("servers", [])
    elif isinstance(config_data, list):
        server_configs_raw = config_data
    else:
        logger.error(f"Invalid config format in {config_file}")
        return []
    
    server_configs = []
    for raw in server_configs_raw:
        try:
            config = MCPServerConfig(
                name=raw["name"],
                url=raw.get("url"),
                transport=raw.get("transport", "streamable_http"),
                headers=raw.get("headers", {}),
                # Support both new "forward_bearer_token" and legacy "requires_auth"
                forward_bearer_token=raw.get("forward_bearer_token", raw.get("requires_auth", False)),
                use_service_token=raw.get("use_service_token", False),
                command=raw.get("command"),
                args=raw.get("args", []),
                env=raw.get("env"),
            )
            server_configs.append(config)
        except (KeyError, TypeError) as e:
            logger.warning(f"Invalid MCP server config: {raw}, error: {e}")
            continue
    
    return server_configs


async def initialize_mcp_tools() -> List[BaseTool]:
    """
    Initialize MCP tools at application startup.
    
    Only loads tools from servers that don't require authentication.
    Auth-required servers are loaded per-request via get_mcp_tools_with_auth().
    
    Returns:
        List of loaded tools from no-auth servers (also cached globally)
    """
    global _mcp_tools, _mcp_loader, _server_configs
    
    _server_configs = _parse_mcp_config()
    
    if not _server_configs:
        _mcp_tools = []
        return []
    
    # Split servers by auth requirement
    no_auth_servers = [s for s in _server_configs if not s.forward_bearer_token]
    auth_servers = [s.name for s in _server_configs if s.forward_bearer_token]
    
    if auth_servers:
        logger.info(f"Servers requiring auth (loaded per-request): {auth_servers}")
    
    if not no_auth_servers:
        logger.info("All MCP servers require auth - tools will be loaded per-request with bearer token")
        _mcp_tools = []
        return []
    
    logger.info(f"Loading tools from {len(no_auth_servers)} no-auth MCP server(s) at startup...")

    # Service-token servers are session-independent, so they load at startup too —
    # with Opey's OWN client-credentials token, never a user's.
    service_token = None
    if any(s.use_service_token for s in no_auth_servers):
        service_token = await service_token_provider.get_token()

    _mcp_loader = MCPToolLoader(servers=no_auth_servers, service_token=service_token)
    
    try:
        _mcp_tools = await _mcp_loader.load_tools()
        logger.info(f"Loaded {len(_mcp_tools)} MCP tools at startup: {[t.name for t in _mcp_tools]}")
        return _mcp_tools
    except MCPConnectionError as e:
        logger.error(f"MCP startup error: {e}")
        _mcp_tools = []
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading MCP tools: {type(e).__name__}: {e}")
        _mcp_tools = []
        return []


def get_mcp_tools() -> List[BaseTool]:
    """
    Get cached MCP tools (loaded at startup).

    Must call initialize_mcp_tools() first (typically at app startup).
    Returns empty list if not initialized or initialization failed.

    Note: For authenticated MCP servers, use get_mcp_tools_with_auth() instead.
    Prefer ensure_mcp_tools() in async code: it recovers from a failed startup load.
    """
    if _mcp_tools is None:
        logger.warning("MCP tools not initialized - call initialize_mcp_tools() first")
        return []
    return _mcp_tools


_last_tools_retry_monotonic: float = 0.0
_TOOLS_RETRY_COOLDOWN_SECONDS = 30.0


async def ensure_mcp_tools() -> List[BaseTool]:
    """
    Cached MCP tools, with lazy recovery from a failed startup load.

    If Opey starts before its MCP server (a stack restart in the wrong order),
    initialize_mcp_tools() caches an empty list and nothing ever retried it:
    every session's graph was built tool-less while /status — which probes the
    MCP server live — showed green. Here an empty cache triggers a reload, at
    most once per cooldown window so a genuinely-down MCP server isn't hammered
    on every request.
    """
    global _last_tools_retry_monotonic
    if _mcp_tools:
        return _mcp_tools
    # Legitimately empty: every configured server loads per-request with auth.
    if _server_configs is not None and not [s for s in _server_configs if not s.forward_bearer_token]:
        return []
    now = time.monotonic()
    if now - _last_tools_retry_monotonic < _TOOLS_RETRY_COOLDOWN_SECONDS:
        return _mcp_tools or []
    _last_tools_retry_monotonic = now
    logger.warning("MCP tools cache is empty - retrying tool load (MCP server may have started after Opey)")
    return await initialize_mcp_tools()


def get_server_configs() -> List[MCPServerConfig]:
    """Get the parsed MCP server configurations."""
    if _server_configs is None:
        return _parse_mcp_config()
    return _server_configs


def get_auth_required_servers() -> List[str]:
    """Get list of server names that require bearer token authentication."""
    configs = get_server_configs()
    return [s.name for s in configs if s.forward_bearer_token]


async def get_mcp_tools_with_auth(bearer_token: Optional[str] = None) -> List[BaseTool]:
    """
    Get MCP tools with optional bearer token authentication.
    
    Creates a new MCP client connection with the provided bearer token.
    Use this for per-request tool access when user has authenticated via OAuth.
    
    Args:
        bearer_token: OAuth bearer token from frontend (optional)
        
    Returns:
        List of LangChain-compatible tools
    """
    configs = get_server_configs()
    if not configs:
        return []

    service_token = None
    if any(s.use_service_token for s in configs):
        service_token = await service_token_provider.get_token()

    return await create_mcp_tools_with_auth(configs, bearer_token, service_token)


async def close_mcp_tools() -> None:
    """Clean up MCP connections during shutdown."""
    global _mcp_tools, _mcp_loader, _server_configs
    
    if _mcp_loader:
        await _mcp_loader.close()
        logger.info("MCP connections closed")
    
    _mcp_tools = None
    _mcp_loader = None
    _server_configs = None
