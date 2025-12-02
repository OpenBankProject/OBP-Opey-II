import os
import uuid
import logging
from typing import Any, Annotated

from fastapi import FastAPI, HTTPException, Request, Response, status, Depends
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse

from langgraph.graph.state import CompiledStateGraph
from langsmith import Client as LangsmithClient

from auth.session import session_cookie, backend, SessionData
from auth.auth import AuthConfig

from service.opey_session import OpeySession

from .streaming import StreamManager
from .streaming_legacy import _parse_input
from .lifecycle import lifespan
from .dependencies import get_auth_config

from schema import (
    ChatMessage,
    Feedback,
    FeedbackResponse,
    StreamInput,
    UserInput,
    convert_message_content_to_string,
    ToolCallApproval,
    SessionCreateResponse,
    UsageInfoResponse,
    SessionUpgradeResponse,
)

from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('opey.service')

# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)

# Setup configuration
from .config import get_cors_config, setup_auth, setup_rate_limiting, get_obp_base_url
from .middleware import setup_middleware

cors_allowed_origins, cors_allowed_methods, cors_allowed_headers = get_cors_config()

# Setup all middleware (includes CORS, rate limiting, error handling, logging, etc.)
setup_middleware(
    app=app,
    cors_allowed_origins=cors_allowed_origins,
    cors_allowed_methods=cors_allowed_methods,
    cors_allowed_headers=cors_allowed_headers
)


from .routers import session, chat, misc
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(misc.router)

# Get OBP base URL for endpoints
obp_base_url = get_obp_base_url()

# Setup rate limiting
setup_rate_limiting(app)
# Rate limiter instance for endpoint decorators
from slowapi import Limiter
limiter: Limiter = app.state.limiter
# Define Exemptions
limiter.exempt(session.create_session)
limiter.exempt(chat.stop_stream)
limiter.exempt(misc.get_status)
limiter.exempt(misc.get_mermaid_diagram)
limiter.exempt(misc.feedback)
