"""
MCP tool integration.

Loads tools from MCP servers and provides them to the agent.
Approval is handled by the simplified approval system in approval.py.
"""

from typing import Any, Optional, List, Dict
from dataclasses import dataclass, field
import logging

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection."""
    name: str  # Server identifier
    transport: str = "sse"  # "sse", "http", or "stdio"
    
    # HTTP/SSE transport
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    
    # stdio transport
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None


class MCPToolLoader:
    """
    Loads tools from MCP servers.
    
    Simple responsibility: connect to servers, get tools, return them.
    Approval logic is handled separately by ApprovalStore.
    """
    
    def __init__(self, servers: List[MCPServerConfig]):
        """
        Args:
            servers: List of server configurations
        """
        self.servers = servers
        self._client: Optional[MultiServerMCPClient] = None
        self._tools: List[BaseTool] = []
    
    async def load_tools(self) -> List[BaseTool]:
        """
        Connect to MCP servers and load available tools.
        
        Returns:
            List of LangChain-compatible tools from all configured servers
        """
        if not self.servers:
            logger.info("No MCP servers configured")
            return []
        
        client_config = self._build_client_config()
        
        logger.info(f"Connecting to {len(self.servers)} MCP server(s)")
        
        # MultiServerMCPClient manages connections internally
        self._client = MultiServerMCPClient(client_config)
        self._tools = await self._client.get_tools()
        logger.info(f"Loaded {len(self._tools)} tools from MCP servers")
        
        return self._tools
    
    def get_tool_names(self) -> List[str]:
        """Get names of all loaded tools."""
        return [t.name for t in self._tools]
    
    def _build_client_config(self) -> Dict[str, Any]:
        """Convert MCPServerConfig list to MultiServerMCPClient format."""
        result: Dict[str, Any] = {}
        
        for server in self.servers:
            config: Dict[str, Any] = {"transport": server.transport}
            
            if server.transport in ("http", "sse"):
                if not server.url:
                    raise ValueError(f"MCP server '{server.name}' requires 'url' for {server.transport} transport")
                config["url"] = server.url
                if server.headers:
                    config["headers"] = server.headers
                    
            elif server.transport == "stdio":
                if not server.command:
                    raise ValueError(f"MCP server '{server.name}' requires 'command' for stdio transport")
                config["command"] = server.command
                config["args"] = server.args
                if server.env:
                    config["env"] = server.env
            else:
                raise ValueError(f"Unknown transport '{server.transport}' for MCP server '{server.name}'")
            
            result[server.name] = config
            
        return result
    
    async def close(self) -> None:
        """Clean up connections."""
        self._client = None
        self._tools = []