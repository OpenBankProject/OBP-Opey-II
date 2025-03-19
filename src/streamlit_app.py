import asyncio
import os
from collections.abc import AsyncGenerator
import json

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from PIL import Image
from client import AgentClient
from schema import ChatMessage, ToolCallApproval

from utils.utils import generate_mermaid_diagram

# A Streamlit app for interacting with the langgraph agent via a simple chat interface.
# The app has three main functions which are all run async:

# - main() - sets up the streamlit app and high level structure
# - draw_messages() - draws a set of chat messages - either replaying existing messages
#   or streaming new ones.
# - handle_feedback() - Draws a feedback widget and records feedback from the user.

# The app heavily uses AgentClient to interact with the agent's FastAPI endpoints.

OBP_favicon = Image.open("src/resources/favicon.ico")
OBP_LOGO = Image.open("src/resources/OBP_full_web.png")
OPEY_AVATAR = Image.open("src/resources/opey-icon.png")
OPEY_LOGO = Image.open("src/resources/opey_logo.png")

APP_TITLE = "Opey Agent Service"


@st.cache_resource
def get_agent_client() -> AgentClient:
    agent_url = os.getenv("AGENT_URL", "http://localhost:5000")
    return AgentClient(agent_url)


async def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=OBP_favicon,
    )

    # Hide the streamlit upper-right chrome
    # st.html(
    #     """
    #     <style>
    #     [data-testid="stStatusWidget"] {
    #             visibility: hidden;
    #             height: 0%;
    #             position: fixed;
    #         }
    #     </style>
    #     """,
    # )
    # if st.get_option("client.toolbarMode") != "minimal":
    #     st.set_option("client.toolbarMode", "minimal")
    #     await asyncio.sleep(0.1)
    #     st.rerun()

    models = {
        "OpenAI GPT-4o-mini (streaming)": "gpt-4o-mini",
        "Gemini 1.5 Flash (streaming)": "gemini-1.5-flash",
        "Claude 3 Haiku (streaming)": "claude-3-haiku",
        "llama-3.1-70b on Groq": "llama-3.1-70b",
    }
    # Config options
    with st.sidebar:
        st.image(OPEY_LOGO, width=300)
        st.header(f"{APP_TITLE}")
        ""
        "Full toolkit for running an AI agent service built with LangGraph, FastAPI and Streamlit"
        with st.popover(":material/settings: Settings", use_container_width=True):
            m = st.radio("LLM to use", options=models.keys())
            model = models[m]
            use_streaming = st.toggle("Stream results", value=True)

        @st.dialog("Architecture")
        def architecture_dialog() -> None:
            try:
                generate_mermaid_diagram("src/resources/agent_architecture.png")
                st.image(
                    "src/resources/agent_architecture.png",
                )
            except Exception as e:
                st.error(f"Error generating architecture diagram: {e}")
                st.write("Graph diagram not available at this time")
            

        if st.button(":material/schema: Architecture", use_container_width=True):
            architecture_dialog()

        with st.popover(":material/policy: Privacy", use_container_width=True):
            st.write(
                "Prompts, responses and feedback in this app are anonymously recorded and saved to LangSmith for product evaluation and improvement purposes only."
            )

        "[View the source code](https://github.com/OpenBankProject/OBP-Opey-II)"
        st.caption(
            "Made by [TESOBE](https://www.tesobe.com/)with inspiration from [Agent Service Toolkit](https://github.com/JoshuaC215/agent-service-toolkit)"
        )
        st.write(OBP_LOGO)

    # Draw existing messages
    if "messages" not in st.session_state:
        st.session_state.messages = []
    messages: list[ChatMessage] = st.session_state.messages
    if "pending_tool_calls" not in st.session_state:
        st.session_state.pending_tool_calls = {}
    if "completed_tool_calls" not in st.session_state:
        st.session_state.completed_tool_calls = {}

    if len(messages) == 0:
        WELCOME = "Hello, I'm Opey! A context informed AI assistant for the Open Bank Project API. Ask me anything about the API and I'll do my best to help you out."
        with st.chat_message(name="ai", avatar=OPEY_AVATAR):
            st.write(WELCOME)

    # draw_messages() expects an async iterator over messages
    async def amessage_iter() -> AsyncGenerator[ChatMessage, None]:
        for m in messages:
            yield m

    await draw_messages(amessage_iter(), thread_id=get_script_run_ctx().session_id)

    if st.session_state.approval_pending:
        st.write("Approve call to API?")
        print(st.session_state.approval_tool_call)
        st.write(st.session_state.approval_tool_call)
        agent_client = get_agent_client()
        # Use a container to hold the buttons
        with st.container():
            approve_col, deny_col = st.columns(2)
            with approve_col:
                if st.button("Approve"):
                    print("Approved request")
                    st.session_state.approval_pending = False
                    stream = agent_client.approve_request_and_stream(
                        thread_id=st.session_state.approval_thread_id,
                        user_input=ToolCallApproval(
                            tool_call_id=st.session_state.approval_tool_call["id"],
                            approval="approve"
                        )
                    )
                    await draw_messages(stream, thread_id=st.session_state.approval_thread_id, is_new=True)
            with deny_col:
                if st.button("Deny"):
                    print("Denied request")
                    st.session_state.approval_pending = False
                    stream = agent_client.approve_request_and_stream(
                        thread_id=st.session_state.approval_thread_id,
                        user_input=ToolCallApproval(
                            tool_call_id=st.session_state.approval_tool_call["id"],
                            approval="deny"
                        )
                    )
                    await draw_messages(stream, thread_id=st.session_state.approval_thread_id, is_new=True)
            st.rerun()

    # Generate new message if the user provided new input
    if user_input := st.chat_input():
        messages.append(ChatMessage(type="human", content=user_input))
        st.chat_message("human").write(user_input)
        agent_client = get_agent_client()
        if use_streaming:
            stream = agent_client.astream(
                message=user_input,
                model=model,
                thread_id=get_script_run_ctx().session_id,
            )
            await draw_messages(stream, thread_id=get_script_run_ctx().session_id, is_new=True)
        
        else:
            response = await agent_client.ainvoke(
                message=user_input,
                model=model,
                thread_id=get_script_run_ctx().session_id,
            )
            messages.append(response)
            st.chat_message("ai").write(response.content)
        st.rerun()  # Clear stale containers

    # If messages have been generated, show feedback widget
    if len(messages) > 0:
        with st.session_state.last_message:
            await handle_feedback()


async def draw_messages(
    messages_agen: AsyncGenerator[ChatMessage | str | dict, None],
    thread_id: str,
    is_new: bool = False,
) -> None:
    """
    Draws a set of chat messages - either replaying existing messages
    or streaming new ones.

    This function has additional logic to handle streaming tokens and tool calls.
    - Use a placeholder container to render streaming tokens as they arrive.
    - Use a status container to render tool calls. Track the tool inputs and outputs
      and update the status container accordingly.

    The function also needs to track the last message container in session state
    since later messages can draw to the same container. This is also used for
    drawing the feedback widget in the latest chat message.

    Args:
        messages_agen: An async iterator over messages to draw.
        thread_id: The thread ID associated with the conversation.
        is_new: Whether the messages are new or not.
    """
    if 'approval_pending' not in st.session_state:
        st.session_state.approval_pending = False
        st.session_state.approval_tool_call = None
        st.session_state.approval_thread_id = None

    # Keep track of the last message container
    last_message_type = None
    st.session_state.last_message = None

    # Placeholder for intermediate streaming tokens
    streaming_content = ""
    streaming_placeholder = None

    # Iterate over the messages and draw them
    while msg := await anext(messages_agen, None):
        # str message represents an intermediate token being streamed
        if isinstance(msg, str):
            # If placeholder is empty, this is the first token of a new message
            if not streaming_placeholder:
                if last_message_type != "ai":
                    last_message_type = "ai"
                    st.session_state.last_message = st.chat_message("ai", avatar=OPEY_AVATAR)
                with st.session_state.last_message:
                    streaming_placeholder = st.empty()

            streaming_content += msg
            streaming_placeholder.write(streaming_content)
            continue
        
        if isinstance(msg, dict):
            if msg["type"] == "keep_alive":
                continue
                

        if not isinstance(msg, ChatMessage):
            st.error(f"Unexpected message type: {type(msg)}")
            st.write(msg)
            continue

        # Match message types
        match msg.type:
            # User messages
            case "human":
                last_message_type = "human"
                st.chat_message("human").write(msg.content)

            # Agent messages
            case "ai":
                if is_new:
                    st.session_state.messages.append(msg)

                if last_message_type != "ai":
                    last_message_type = "ai"
                    st.session_state.last_message = st.chat_message("ai", avatar=OPEY_AVATAR)

                with st.session_state.last_message:
                    if msg.content:
                        if streaming_placeholder:
                            streaming_placeholder.write(msg.content)
                            streaming_content = ""
                            streaming_placeholder = None
                        else:
                            st.write(msg.content)
                    
                    
                    #if msg.original["metadata"]["langgraph_node"] in ["retrieve_endpoints"]


                    #if msg.original["metadata"]["langgraph_node"] in ["retrieve_endpoints"]

                    if msg.tool_calls:
                        # Create a status container for each tool call and store the
                        # status container by ID to ensure results are mapped to the
                        # correct status container.
                        print(f"Received tool calls: {msg.tool_calls}")
                        pending_tool_calls = st.session_state.pending_tool_calls
                        for tool_call in msg.tool_calls:
                            status = st.status(
                                f"""Tool Call: {tool_call["name"]}""",
                                state="running" if is_new else "complete",
                            )
                            pending_tool_calls[tool_call["id"]] = status
                            status.write("Input:")
                            status.write(tool_call["args"])


                        print(f"Waiting for {len(pending_tool_calls)} call(s) to finish\n")
                        
            case "tool":
                pending_tool_calls = st.session_state.pending_tool_calls
                completed_tool_calls = st.session_state.completed_tool_calls
                print(f"Received tool message: {msg}")
                if msg.tool_call_id in pending_tool_calls.keys() and not st.session_state.approval_pending:
                    if msg.tool_approval_request:
                        print("Received tool approval request")
                        st.session_state.approval_tool_call = msg.tool_calls[0]
                        st.session_state.approval_pending = True
                        st.session_state.approval_thread_id = thread_id
                    else:
                        if is_new:
                            st.session_state.messages.append(msg)
                        status = pending_tool_calls[msg.tool_call_id]
                        status.write("Output:")
                        try:
                            json_formatted = json.loads(msg.content)
                        except ValueError as e:
                            print(f"Error parsing tool output as JSON: {e}")
                            json_formatted = msg.content

                        status.write(json_formatted)
                        status.update(state="complete")
                        completed_tool_calls[msg.tool_call_id] = pending_tool_calls.pop(msg.tool_call_id)
                # Handle other message types if necessary
            case _:
                st.error(f"Unexpected ChatMessage type: {msg.type}")
                st.write(msg)
                st.stop()

async def handle_feedback() -> None:
    """Draws a feedback widget and records feedback from the user."""

    # Keep track of last feedback sent to avoid sending duplicates
    if "last_feedback" not in st.session_state:
        st.session_state.last_feedback = (None, None)

    latest_run_id = st.session_state.messages[-1].run_id
    feedback = st.feedback("stars", key=latest_run_id)

    # If the feedback value or run ID has changed, send a new feedback record
    if feedback is not None and (latest_run_id, feedback) != st.session_state.last_feedback:
        # Normalize the feedback value (an index) to a score between 0 and 1
        normalized_score = (feedback + 1) / 5.0

        agent_client = get_agent_client()
        await agent_client.acreate_feedback(
            run_id=latest_run_id,
            key="human-feedback-stars",
            score=normalized_score,
            kwargs={"comment": "In-line human feedback"},
        )
        st.session_state.last_feedback = (latest_run_id, feedback)
        st.toast("Feedback recorded", icon=":material/reviews:")

if __name__ == "__main__":
    asyncio.run(main())