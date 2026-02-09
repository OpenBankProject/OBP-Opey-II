from dataclasses import dataclass
from typing import Any, Optional

from src.agent.components.tools.mcp.elicitation import PendingElicitation


@dataclass
class ConsentRequest:
    """Parsed consent elicitation with OBP-specific fields."""
    elicitation_id: str
    operation_id: str
    message_prompt: str
    required_roles: list[dict[str, Any]]
    server_name: str
    tool_name: Optional[str]
    
    @classmethod
    def from_pending(cls, pending: PendingElicitation) -> "ConsentRequest":
        """
        Parse a PendingElicitation into a ConsentRequest.
        
        Expects pending.message to have:
        {
            "operation_id": str,
            "message_prompt": str,
            "required_roles": list[dict],
            ...
        }
        """
        msg = pending.message
        return cls(
            elicitation_id=pending.elicitation_id,
            operation_id=pending.message.get("operation_id", ""),
            message_prompt=pending.message.get("message_prompt", ""),
            required_roles=pending.message.get("required_roles", []),
            server_name=pending.server_name,
            tool_name=pending.tool_name,
        )
        
    @classmethod
    def is_consent_elicitation(cls, pending: PendingElicitation) -> bool:
        """Check if a PendingElicitation is a consent request."""
        msg = pending.message
        return all(k in msg for k in ("operation_id", "message_prompt", "required_roles"))
    
