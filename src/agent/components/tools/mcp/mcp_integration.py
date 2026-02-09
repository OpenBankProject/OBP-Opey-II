"""
MCP tool integration.

Loads tools from MCP servers and provides them to the agent.

Supports two authentication modes:
1. Bearer token pass-through: Frontend handles OAuth, passes token to agent,
   which forwards it to MCP servers via Authorization header using interceptors.
2. No auth: For MCP servers that don't require authentication.

Architecture (Bearer Token Pass-Through):
- Frontend performs OAuth flow with IdP (e.g., OBP-OIDC)
- Frontend sends bearer token to Agent API
- Agent stores token in session/config
- Tool interceptor injects token into MCP requests at invocation time
- MCP server validates token via JWKS
"""

from typing import Any, Optional, List, Dict, Callable, Awaitable
from dataclasses import dataclass, field
import logging

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from .elicitation import ElicitationCoordinator

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection."""
    name: str  # Server identifier
    transport: str = "streamable_http"  # "sse", "http", "streamable_http", or "stdio"
    
    # HTTP/SSE transport
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    
    # Whether this server requires bearer token authentication
    # If True, the bearer token from the session will be added to requests
    requires_auth: bool = False
    
    # stdio transport
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None


class MCPToolLoader:
    """
    Loads tools from MCP servers.
    
    Supports two modes:
    1. Static tools (no auth): Load tools once at startup
    2. Per-request tools (with bearer token): Create client per-request with user's token
    """
    
    def __init__(
        self, servers: List[MCPServerConfig],
        bearer_token: Optional[str] = None,
        elicitation_coordinator: Optional[ElicitationCoordinator] = None,
    ):
        """
        Args:
            servers: List of server configurations
            bearer_token: Optional bearer token for authenticated requests.
                         If provided, adds Authorization header to servers with requires_auth=True.
        """
        self.servers = servers
        self.bearer_token = bearer_token
        self.elicitation_coordinator = elicitation_coordinator
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
        client_kwargs: dict[str, Any] = {}
        
        if self.elicitation_coordinator:
            from langchain_mcp_adapters.callbacks import Callbacks
            client_kwargs["callbacks"] = Callbacks(
                on_elicitation=self.elicitation_coordinator.handle_elicitation
            )
        
        logger.info(f"Connecting to {len(self.servers)} MCP server(s)")
        
        # MultiServerMCPClient manages connections internally
        self._client = MultiServerMCPClient(client_config, **client_kwargs)
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
                
                # Build headers, injecting bearer token if needed
                headers = dict(server.headers)  # Copy to avoid mutating config
                if server.requires_auth and self.bearer_token:
                    headers["Authorization"] = f"Bearer {self.bearer_token}"
                    logger.debug(f"Added bearer token to '{server.name}' headers")
                elif server.requires_auth and not self.bearer_token:
                    logger.warning(f"MCP server '{server.name}' requires auth but no bearer token provided")
                
                if headers:
                    config["headers"] = headers
                    
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


async def create_mcp_tools_with_auth(
    servers: List[MCPServerConfig], 
    bearer_token: Optional[str] = None
) -> List[BaseTool]:
    """
    Factory function to create MCP tools with optional bearer token authentication.
    
    Use this for per-request tool creation when user has a bearer token.
    
    Args:
        servers: List of MCP server configurations
        bearer_token: OAuth bearer token from frontend (optional)
        
    Returns:
        List of LangChain-compatible tools
    """
    loader = MCPToolLoader(servers=servers, bearer_token=bearer_token)
    try:
        return await loader.load_tools()
    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}")
        return []


def create_bearer_token_interceptor(
    bearer_token: str,
    server_names: Optional[List[str]] = None,
) -> Callable:
    """
    Create a tool interceptor that injects bearer token into MCP requests.
    
    This interceptor modifies the request headers to include an Authorization
    header with the bearer token. It's used for MCP servers that validate
    tokens via JWKS (bearer-only auth mode).
    
    Args:
        bearer_token: OAuth bearer token to inject
        server_names: Optional list of server names to apply the token to.
                     If None, applies to all servers.
    
    Returns:
        A tool interceptor function compatible with langchain-mcp-adapters
        
    Example:
        interceptor = create_bearer_token_interceptor("eyJhbGci...")
        client = MultiServerMCPClient(config, tool_interceptors=[interceptor])
    """
    from langchain_mcp_adapters.interceptors import MCPToolCallRequest
    from mcp.types import CallToolResult
    
    async def bearer_token_interceptor(
        request: MCPToolCallRequest,
        handler: Callable[[MCPToolCallRequest], Awaitable[CallToolResult]],
    ) -> CallToolResult:
        """Inject bearer token into request headers."""
        # Check if we should apply to this server
        if server_names is not None and request.server_name not in server_names:
            return await handler(request)
        
        # Inject bearer token into headers
        current_headers = request.headers or {}
        updated_headers = {
            **current_headers,
            "Authorization": f"Bearer {bearer_token}",
        }
        modified_request = request.override(headers=updated_headers)
        
        logger.debug(f"Injected bearer token for MCP server '{request.server_name}'")
        return await handler(modified_request)
    
    return bearer_token_interceptor