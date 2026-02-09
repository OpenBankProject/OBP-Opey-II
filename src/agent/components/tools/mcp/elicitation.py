"""
Coordinates MCP elicitation requests with frontend responses.

Bridges the gap between the on_elicitation callback and the HTTP endpoint that recieves a user response.
"""

import asyncio
import json
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from mcp.shared.context import RequestContext
from mcp.types import ElicitRequestParams, ElicitResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # seconds


@dataclass 
class PendingElicitation:
    """An elicitation request awaiting an external response."""
    elicitation_id: str
    message: dict[str, Any]
    server_name: str
    tool_name: Optional[str]
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _result: Optional[ElicitResult] = field(default=None, repr=False)
    
    def resolve(self, result: ElicitResult) -> None:
        self._result = result
        self._event.set()
    
    async def wait(self, timeout: float) -> ElicitResult:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Elicitation {self.elicitation_id} timed out after {timeout} seconds")
            return ElicitResult(action="decline", content={"reason": "timeout"})
        
        if self._result is None:
            logger.error(f"Elicitation {self.elicitation_id} was resolved without a result")
            return ElicitResult(action="decline", content={"reason": "no_result"})
        return self._result


class ElicitationCoordinator:
    """
    Manages pending MCP elicitation requests.
    
    Uses a class-level registry so the consent router can resolve any
    elicitation_id to its coordinator without per-session dependency injection.
    
    Flow:
    1. on_elicitation callback calls handle_elicitation() — blocks on PendingElicitation
    2. Coordinator pushes PendingElicitation to outgoing_events queue
    3. Consumer (e.g. StreamManager) drains queue and notifies frontend
    4. External caller invokes respond() — unblocks the waiting callback
    """
    
    # Class-level registry: elicitation_id → coordinator instance
    _registry: dict[str, "ElicitationCoordinator"] = {}
    
    @classmethod
    def find_by_elicitation_id(cls, elicitation_id: str) -> Optional["ElicitationCoordinator"]:
        """Look up the coordinator that owns a given elicitation_id."""
        return cls._registry.get(elicitation_id)
    
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self._pending: dict[str, PendingElicitation] = {}
        self._timeout = timeout
        self.outgoing_events: asyncio.Queue[PendingElicitation] = asyncio.Queue()
        
    async def handle_elicitation(
        self, 
        mcp_context: RequestContext,
        params: ElicitRequestParams,
        context: Any,
    ) -> ElicitResult:
        """MCP elicitation callback. Blocks until respond() is called or timeout occurs."""
        try: 
            message = json.loads(params.message)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse elicitation message: {e}")
            return ElicitResult(action="decline", content={"reason": "invalid_message"})
        
        server_name = getattr(context, "server_name", "unknown_server")
        tool_name = getattr(context, "tool_name", None)
        
        elicitation_id = str(uuid.uuid4())
        pending = PendingElicitation(
            elicitation_id=elicitation_id,
            message=message,
            server_name=server_name,
            tool_name=tool_name,
        )
        self._pending[elicitation_id] = pending
        ElicitationCoordinator._registry[elicitation_id] = self
        
        await self.outgoing_events.put(pending)
        logger.info(f"Elicitation {elicitation_id} awaiting response (server={server_name}, tool={tool_name})")
        
        try:
            return await pending.wait(self._timeout)
        finally: 
            self._pending.pop(elicitation_id, None)
            ElicitationCoordinator._registry.pop(elicitation_id, None)
            
    
    def respond(self, elicitation_id: str, result: ElicitResult) -> bool:
        """Resolve a pending elicitation. Returns False if not found."""
        pending = self._pending.get(elicitation_id)
        if not pending:
            logger.warning(f"Received response for unknown elicitation_id: {elicitation_id}")
            return False
        
        pending.resolve(result)
        logger.info(f"Elicitation {elicitation_id} resolved with action={result.action}")
        return True
        