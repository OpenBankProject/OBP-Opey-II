import json
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any
import uuid
import logging

from fastapi import FastAPI, HTTPException, Request, Response, status, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langsmith import Client as LangsmithClient

from auth.auth import OBPConsentAuth, AuthConfig
from auth.session import cookie, backend, verifier, SessionData

from .streaming import (
    _parse_input,
    _process_stream_event,
)

from agent import opey_graph, opey_graph_no_obp_tools
from schema import (
    ChatMessage,
    Feedback,
    FeedbackResponse,
    StreamInput,
    UserInput,
    convert_message_content_to_string,
    ToolCallApproval,
)

logger = logging.getLogger()

if os.getenv("DISABLE_OBP_CALLING") == "true":
    logger.info("Disabling OBP tools: Calls to the OBP-API will not be available")
    opey_instance = opey_graph_no_obp_tools
else:
    logger.info("Enabling OBP tools: Calls to the OBP-API will be available")
    opey_instance = opey_graph

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Construct agent with Sqlite checkpointer
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as saver:
        opey_instance.checkpointer = saver
        app.state.agent = opey_instance
        yield
    # context manager will clean up the AsyncSqliteSaver on exit


app = FastAPI(lifespan=lifespan)

# Setup CORS policy
if cors_allowed_origins := os.getenv("CORS_ALLOWED_ORIGINS"):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    raise ValueError("CORS_ALLOWED_ORIGINS environment variable must be set")

# Define Allowed Authentication methods,
# Currently only OBP consent is allowed
auth_config = AuthConfig({
    "obp_consent": OBPConsentAuth(),
})

# Middleware for checking the Authorization header, i.e. OBP consent
obp_base_url = os.getenv('OBP_BASE_URL')
jwk_url = f'{obp_base_url}/obp/v5.1.0/certs'

# @app.middleware("http")
# async def check_auth_header(request: Request, call_next: Callable) -> Response:
#     request_body = await request.body()
#     logger.debug("This is coming from the auth middleware")
#     logger.debug(f"Request: {request_body}")

#     # Check if the request has a consent JWT in the headers
#     if request.headers.get("Consent-JWT"):
#         token = request.headers.get("Consent-JWT")
#         if not await auth_config.obp_consent.acheck_auth(token):
#             return Response(status_code=401, content="Invalid token")
#     else:
#         return Response(status_code=401, content="Missing Authorization headers, Must be one of ['Consent-JWT']")

#     # TODO: Add more auth methods here if needed
        
#     response = await call_next(request)
#     logger.debug(f"Response: {response}")
#     return response

@app.post("/create-session")
async def create_session(request: Request, response: Response) -> Response:
    """
    Create a session for the user using the OBP consent JWT.
    """
    # Get the consent JWT from the request
    consent_jwt = request.headers.get("Consent-JWT")
    if not consent_jwt:
        return Response(status_code=401, content="Missing Authorization headers, Must be one of ['Consent-JWT']")

    # Check if the consent JWT is valid
    if not await auth_config.obp_consent.acheck_auth(consent_jwt):
        return Response(status_code=401, content="Invalid Consent-JWT")

    session_id = uuid.uuid4()

    # Create a session using the OBP consent JWT
    session_data = SessionData(
        consent_jwt=consent_jwt,
    )

    await backend.create(session_id, session_data)
    cookie.attach_to_response(response, session_id)

    response.status_code = 200
    response.body = b"session created"

    return response


@app.post("/delete-session")
async def delete_session(response: Response, session_id: uuid.UUID = Depends(cookie)):
    await backend.delete(session_id)
    cookie.delete_from_response(response)
    response.status_code = 200
    response.body = b"session deleted"
    return response


@app.get("/status", dependencies=[Depends(cookie)])
async def get_status(session_data: SessionData = Depends(verifier)) -> dict[str, str]:
    """Health check endpoint."""
    if not app.state.agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    return {"status": "ok"}

@app.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """
    Invoke the agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    """
    agent: CompiledStateGraph = app.state.agent
    kwargs, run_id = _parse_input(user_input)
    try:
        response = await agent.ainvoke(**kwargs)
        output = ChatMessage.from_langchain(response["messages"][-1])
        logger.info(f"Replied to thread_id {kwargs['config']['configurable']['thread_id']} with message:\n\n {output.content}\n")
        output.run_id = str(run_id)
        return output
    except Exception as e:
        logging.error(f"Error invoking agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def message_generator(user_input: StreamInput) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    agent: CompiledStateGraph = app.state.agent
    kwargs, run_id = _parse_input(user_input)
    config = kwargs["config"]

    print(f"------------START STREAM-----------\n\n")
    # Process streamed events from the graph and yield messages over the SSE stream.
    async for event in agent.astream_events(**kwargs, version="v2"):
        async for msg in _process_stream_event(event, user_input, str(run_id)):
            yield msg

    # Interruption for human in the loop
    # Wait for user approval via HTTP request
    agent_state = await agent.aget_state(config)
    messages = agent_state.values.get("messages", [])
    print(f"next node: {agent_state.next}")
    tool_call_message = messages[-1] if messages else None
    
    if not tool_call_message or not tool_call_message.tool_calls:
        pass
    else:
        print(f"Tool call message: {tool_call_message}\n")
        tool_call = tool_call_message.tool_calls[0]
        print(f"Waiting for approval of tool call: {tool_call}\n")

        tool_approval_message = ChatMessage(type="tool", tool_approval_request=True, tool_call_id=tool_call["id"], content="", tool_calls=[tool_call])

        yield f"data: {json.dumps({'type': 'message', 'content': tool_approval_message.model_dump()})}\n\n"
    

    yield "data: [DONE]\n\n"


def _sse_response_example() -> dict[int, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@app.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream_agent(user_input: StreamInput) -> StreamingResponse:
    """
    Stream the agent's response to a user input, including intermediate messages and tokens.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    """
    logger.debug(f"Received stream request: {user_input}")

    return StreamingResponse(message_generator(user_input), media_type="text/event-stream")


@app.post("/approval/{thread_id}", response_class=StreamingResponse, responses=_sse_response_example())
async def user_approval(user_approval_response: ToolCallApproval, thread_id: str) -> StreamingResponse:
    print(f"[DEBUG] Approval endpoint user_response: {user_approval_response}\n")
    
    agent: CompiledStateGraph = app.state.agent

    agent_state = await agent.aget_state({"configurable": {"thread_id": thread_id}})

    if user_approval_response.approval == "deny":
        # Answer as if we were the obp requests tool node
        await agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [ToolMessage(content="User denied request to OBP API", tool_call_id=user_approval_response.tool_call_id)]},
            as_node="tools",
        )
    else:
        # If approved, just continue to the OBP requests node
        await agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            values=None,
            as_node="human_review",
        )

    print(f"[DEBUG] Agent state: {agent_state}\n")
    
    user_input = StreamInput(
        message="",
        thread_id=thread_id,
        is_tool_call_approval=True,
    )


    return StreamingResponse(message_generator(user_input), media_type="text/event-stream")


@app.post("/feedback")
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

# @app.post("/auth")
# async def auth(consent_auth_body: ConsentAuthBody, response: Response):
#     """ 
#     Authorize Opey using an OBP consent
#     """
#     logger.debug("Authorizing Opey using an OBP consent")
#     version = os.getenv("OBP_API_VERSION")
#     consent_challenge_answer_path = f"/obp/{version}/banks/gh.29.uk/consents/{consent_auth_body.consent_id}/challenge"
    
#     # Check consent challenge answer
#     try:
#         obp_response = await obp_requests("POST", consent_challenge_answer_path, json.dumps({"answer": consent_auth_body.consent_challenge_answer}))
#     except Exception as e:
#         logger.error(f"Error in /auth endpoint: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

#     if obp_response and not (200 <= obp_response.status < 300):
#         logger.debug("Welp, we got an error from OBP")
#         message = await obp_response.text()
#         raise HTTPException(status_code=obp_response.status, detail=message)
    
#     try:
#         payload = {
#             "consent_id": consent_auth_body.consent_id,
#         }
#         opey_jwt = sign_jwt(payload)
#     except Exception as e:
#         logger.debug("Looks like signing the JWT failed OMG")
#         logger.error(f"Error in /auth endpoint: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

#     print("got consent jwt")
#     # Set the JWT cookie
#     response.set_cookie(key="jwt", value=opey_jwt, httponly=False, samesite='lax', secure=False)
#     return AuthResponse(success=True)