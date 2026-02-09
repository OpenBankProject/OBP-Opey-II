"""
Consent elicitation HTTP endpoint.

Receives frontend consent responses and resolves the corresponding
pending MCP elicitation, unblocking the tool call.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Literal, Optional
import logging

from auth.session import session_cookie
from agent.components.tools.mcp.elicitation import ElicitationCoordinator
from mcp.types import ElicitResult

logger = logging.getLogger("opey.service.routers.consent")

router = APIRouter(
    tags=["consent"],
    dependencies=[Depends(session_cookie)],
)


class ConsentResponse(BaseModel):
    """Frontend response to a consent elicitation request."""
    elicitation_id: str = Field(description="ID of the elicitation being responded to")
    action: Literal["accept", "decline", "cancel"] = Field(
        description="User decision: 'accept', 'decline', or 'cancel'",
    )
    consent_jwt: Optional[str] = Field(
        default=None,
        description="Consent JWT from OBP (required when action is 'accept')",
    )


class ConsentResponseResult(BaseModel):
    """Response confirming the consent was processed."""
    status: str
    elicitation_id: str


@router.post(
    "/consent-response",
    response_model=ConsentResponseResult,
    status_code=status.HTTP_200_OK,
    summary="Submit a consent decision for an MCP elicitation",
)
async def submit_consent_response(body: ConsentResponse) -> ConsentResponseResult:
    """
    Resolve a pending MCP consent elicitation.

    The consent_jwt is forwarded to the MCP server via the elicitation
    result and never reaches the LLM provider.
    """
    coordinator = ElicitationCoordinator.find_by_elicitation_id(body.elicitation_id)
    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending elicitation found for id: {body.elicitation_id}",
        )

    content = {}
    if body.consent_jwt is not None:
        content["consent_jwt"] = body.consent_jwt

    result = ElicitResult(action=body.action, content=content or None)
    resolved = coordinator.respond(body.elicitation_id, result)

    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Elicitation {body.elicitation_id} already resolved or expired",
        )

    logger.info(f"Consent response submitted: elicitation_id={body.elicitation_id}, action={body.action}")
    return ConsentResponseResult(status="ok", elicitation_id=body.elicitation_id)
