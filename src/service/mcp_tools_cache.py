"""
Application-level MCP tools cache.

Loads MCP server configurations at startup. Tools can be loaded:
1. At startup (for servers that don't require auth)
2. Per-request with bearer token (for servers requiring user authentication)
"""
import os
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from langchain_core.tools import BaseTool
from agent.components.tools import MCPToolLoader, MCPServerConfig, create_mcp_tools_with_auth

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
                requires_auth=raw.get("requires_auth", False),
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
    
    Call this from FastAPI's lifespan handler. Tools are cached
    and available via get_mcp_tools() for all sessions.
    
    Note: For servers with requires_auth=True, tools are loaded but
    will fail at runtime if no bearer token is provided. Use
    get_mcp_tools_with_auth() for authenticated access.
    
    Returns:
        List of loaded tools (also cached globally)
    """
    global _mcp_tools, _mcp_loader, _server_configs
    
    _server_configs = _parse_mcp_config()
    
    if not _server_configs:
        _mcp_tools = []
        return []
    
    # Log which servers require auth
    auth_servers = [s.name for s in _server_configs if s.requires_auth]
    if auth_servers:
        logger.info(f"Servers requiring bearer token auth: {auth_servers}")
    
    logger.info(f"Loading tools from {len(_server_configs)} MCP server(s)...")
    
    _mcp_loader = MCPToolLoader(servers=_server_configs)
    
    try:
        _mcp_tools = await _mcp_loader.load_tools()
        logger.info(f"Loaded {len(_mcp_tools)} MCP tools: {[t.name for t in _mcp_tools]}")
        return _mcp_tools
    except ExceptionGroup as eg:
        # Extract nested exceptions from TaskGroup/ExceptionGroup
        logger.error(f"Failed to load MCP tools: {eg}")
        for i, exc in enumerate(eg.exceptions):
            logger.error(f"  Sub-exception {i+1}: {type(exc).__name__}: {exc}")
        _mcp_tools = []
        return []
    except Exception as e:
        logger.error(f"Failed to load MCP tools: {type(e).__name__}: {e}")
        _mcp_tools = []
        return []


def get_mcp_tools() -> List[BaseTool]:
    """
    Get cached MCP tools (loaded at startup).
    
    Must call initialize_mcp_tools() first (typically at app startup).
    Returns empty list if not initialized or initialization failed.
    
    Note: For authenticated MCP servers, use get_mcp_tools_with_auth() instead.
    """
    if _mcp_tools is None:
        logger.warning("MCP tools not initialized - call initialize_mcp_tools() first")
        return []
    return _mcp_tools


def get_server_configs() -> List[MCPServerConfig]:
    """Get the parsed MCP server configurations."""
    if _server_configs is None:
        return _parse_mcp_config()
    return _server_configs


def get_auth_required_servers() -> List[str]:
    """Get list of server names that require bearer token authentication."""
    configs = get_server_configs()
    return [s.name for s in configs if s.requires_auth]


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
    
    return await create_mcp_tools_with_auth(configs, bearer_token)


async def close_mcp_tools() -> None:
    """Clean up MCP connections during shutdown."""
    global _mcp_tools, _mcp_loader, _server_configs
    
    if _mcp_loader:
        await _mcp_loader.close()
        logger.info("MCP connections closed")
    
    _mcp_tools = None
    _mcp_loader = None
    _server_configs = None
