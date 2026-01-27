from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from fastapi import HTTPException
from langsmith import Client as LangsmithClient
from pathlib import Path
from schema import Feedback, FeedbackResponse, UsageInfoResponse
from typing import Any, Annotated
from ..opey_session import OpeySession
from ..dependencies import get_opey_session
from auth.session import session_cookie
import logging

logger = logging.getLogger('opey.service.routers.misc')

router = APIRouter()

@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Health check endpoint with usage information."""

    status_info = {
        "status": "ok",
    }

    return status_info

@router.get("/mermaid_diagram", dependencies=[Depends(session_cookie)])
async def get_mermaid_diagram(opey_session: Annotated[OpeySession, Depends(get_opey_session)]) -> FileResponse:
    svg_path = Path("../resources/mermaid_diagram.svg")
    
    try:
        if not svg_path.parent.exists():
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            
        import mermaid
        mermaid_graph = opey_session.graph.get_graph().draw_mermaid()
        
        mermaid_svg = mermaid.Mermaid(mermaid_graph).to_svg(svg_path)
        logger.info(f"Generated mermaid diagram at {svg_path}")
        
    except Exception as e:
        logger.error(f"Error generating mermaid diagram: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate mermaid diagram")

    return FileResponse(svg_path, media_type="image/svg+xml")

@router.post("/feedback", dependencies=[Depends(session_cookie)])#
async def feedback(feedback: Feedback) -> FeedbackResponse:
    """
    Record feedback for a run to LangSmith.

    This is a simple wrapper for the LangSmith create_feedback API, so the
    credentials can be stored and managed in the service rather than the client.
    See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
    """
    client = LangsmithClient()
    kwargs = feedback.kwargs or {}
    client.create_feedback(
        run_id=feedback.run_id,
        key=feedback.key,
        score=feedback.score,
        **kwargs,
    )
    return FeedbackResponse()


@router.get("/usage", dependencies=[Depends(session_cookie)])
async def get_usage(opey_session: Annotated[OpeySession, Depends(get_opey_session)]) -> UsageInfoResponse:
    """
    Get detailed usage information for the current session.
    """
    usage_info = opey_session.get_usage_info()
    return UsageInfoResponse(**usage_info)