"""
MCP tool integration.

Loads tools from MCP servers and provides them to the agent.
Approval is handled by the simplified approval system in approval.py.

Supports OAuth 2.1 with Dynamic Client Registration (DCR) for servers
that require authenticated access.
"""

from typing import Any, Optional, List, Dict, Literal
from dataclasses import dataclass, field
import logging

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


@dataclass
class OAuthConfig:
    """OAuth 2.1 configuration for MCP server authentication via Dynamic Client Registration."""
    
    scopes: Optional[List[str]] = None
    client_name: str = "OBP-Opey MCP Client"
    callback_port: Optional[int] = None
    
    # Storage strategy: "memory", "redis", "encrypted_disk", etc.
    storage_type: Literal["memory", "redis", "encrypted_disk"] = "memory" # Default to in-memory storage DEV ONLY
    
    # For Redis Storage
    redis_key_prefix: Optional[str] = "mcp:oauth:tokens"
    
    # For encrypted disk storage of OAuth tokens
    token_storage_path: Optional[str] = None
    encryption_key_env: Optional[str] = "MCP_TOKEN_ENCRYPTION_KEY"  # Env var name containing encryption key


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection."""
    name: str  # Server identifier
    transport: str = "sse"  # "sse", "http", "streamable_http", or "stdio"
    
    # HTTP/SSE transport
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    
    # OAuth authentication (for HTTP-based transports)
    # Can be "oauth" for auto-config, or an OAuthConfig for custom settings
    oauth: Optional[OAuthConfig] = None
    
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
            
            if server.transport in ("http", "sse", "streamable_http"):
                if not server.url:
                    raise ValueError(f"MCP server '{server.name}' requires 'url' for {server.transport} transport")
                config["url"] = server.url
                if server.headers:
                    config["headers"] = server.headers
                
                # Configure OAuth authentication if specified
                if server.oauth is not None:
                    auth = self._build_oauth_auth(server)
                    if auth is not None:
                        config["auth"] = auth
                    
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
    
    def _build_oauth_auth(self, server: MCPServerConfig) -> Optional[Any]:
        """
        Build OAuth authentication handler for the server.
        
        Uses FastMCP's OAuth helper which implements httpx.Auth and handles:
        - OAuth server discovery via /.well-known/oauth-authorization-server
        - Dynamic Client Registration (RFC 7591)
        - Authorization Code flow with PKCE
        - Token caching and refresh
        
        Returns:
            An httpx.Auth compatible object, or None if OAuth is not available
        """
        if server.oauth is None or server.url is None:
            return None
        
        try:
            from fastmcp.client.auth import OAuth
        except ImportError:
            logger.warning(
                f"fastmcp package not installed. OAuth authentication for "
                f"server '{server.name}' will be skipped. Install with: pip install fastmcp"
            )
            return None
        
        from .oauth import create_token_storage
        
        logger.info(f"Configuring OAuth for MCP server '{server.name}'")
        
        oauth_config = server.oauth
        oauth_kwargs: Dict[str, Any] = {
            "mcp_url": server.url,
            "client_name": oauth_config.client_name,
        }
        
        if oauth_config.scopes:
            oauth_kwargs["scopes"] = oauth_config.scopes
        
        if oauth_config.callback_port:
            oauth_kwargs["callback_port"] = oauth_config.callback_port
        
        token_storage = create_token_storage(
            server_name=server.name,
            storage_type=oauth_config.storage_type,
            redis_key_prefix=oauth_config.redis_key_prefix,
            token_storage=oauth_config.token_storage_path,
            encryption_key_env=oauth_config.encryption_key_env,
        )
        
        if token_storage is not None:
            oauth_kwargs["token_storage"] = token_storage
            
        logger.info(f"OAuth DCR for '{server.name}' using {oauth_config.storage_type} storage")
        return OAuth(**oauth_kwargs)
    
    async def close(self) -> None:
        """Clean up connections."""
        self._client = None
        self._tools = []