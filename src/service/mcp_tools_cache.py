"""
Application-level MCP tools cache.

Loads MCP tools once at startup and provides them to all sessions.
This avoids the async-in-sync problem of loading tools per-session.
"""
import os
import json
import logging
from typing import List, Optional

from langchain_core.tools import BaseTool
from agent.components.tools import MCPToolLoader, MCPServerConfig

logger = logging.getLogger(__name__)

# Module-level cache
_mcp_tools: Optional[List[BaseTool]] = None
_mcp_loader: Optional[MCPToolLoader] = None


def _parse_mcp_config() -> List[MCPServerConfig]:
    """Parse MCP_SERVERS environment variable into config objects."""
    mcp_config_str = os.getenv("MCP_SERVERS", "[]")
    
    try:
        server_configs_raw = json.loads(mcp_config_str)
    except json.JSONDecodeError:
        logger.warning("Invalid MCP_SERVERS JSON, skipping MCP tools")
        return []
    
    if not server_configs_raw:
        logger.info("No MCP servers configured")
        return []
    
    server_configs = []
    for raw in server_configs_raw:
        try:
            config = MCPServerConfig(
                name=raw["name"],
                url=raw.get("url"),
                transport=raw.get("transport", "sse"),
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
    
    Returns:
        List of loaded tools (also cached globally)
    """
    global _mcp_tools, _mcp_loader
    
    server_configs = _parse_mcp_config()
    
    if not server_configs:
        _mcp_tools = []
        return []
    
    logger.info(f"Loading tools from {len(server_configs)} MCP server(s)...")
    
    _mcp_loader = MCPToolLoader(servers=server_configs)
    
    try:
        _mcp_tools = await _mcp_loader.load_tools()
        logger.info(f"Loaded {len(_mcp_tools)} MCP tools: {[t.name for t in _mcp_tools]}")
        return _mcp_tools
    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}")
        _mcp_tools = []
        return []


def get_mcp_tools() -> List[BaseTool]:
    """
    Get cached MCP tools.
    
    Must call initialize_mcp_tools() first (typically at app startup).
    Returns empty list if not initialized or initialization failed.
    """
    if _mcp_tools is None:
        logger.warning("MCP tools not initialized - call initialize_mcp_tools() first")
        return []
    return _mcp_tools


async def close_mcp_tools() -> None:
    """Clean up MCP connections during shutdown."""
    global _mcp_tools, _mcp_loader
    
    if _mcp_loader:
        await _mcp_loader.close()
        logger.info("MCP connections closed")
    
    _mcp_tools = None
    _mcp_loader = None
