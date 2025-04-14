from schema import (
    ChatMessage,
    Feedback,
    FeedbackResponse,
    StreamInput,
    UserInput,
    convert_message_content_to_string,
    ToolCallApproval,
)
from typing import Any, AsyncGenerator
import uuid
import json
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import ChatMessage
from langchain_core.runnables.schema import StreamEvent

def _parse_input(user_input: UserInput) -> tuple[dict[str, Any], uuid.UUID]:
    run_id = uuid.uuid4()
    thread_id = user_input.thread_id or str(uuid.uuid4())
    # If this is a tool call approval, we don't need to send any input to the agent.
    if user_input.is_tool_call_approval:
        _input = None
    else:
        input_message = ChatMessage(type="human", content=user_input.message)
        _input = {"messages": [input_message.to_langchain()]}
    
    kwargs = {
        "input": _input,
        "config": RunnableConfig(
            configurable={"thread_id": thread_id}, run_id=run_id
        ),
    }
    return kwargs, run_id


def _remove_tool_calls(content: str | list[str | dict]) -> str | list[str | dict]:
    """Remove tool calls from content."""
    if isinstance(content, str):
        return content
    # Currently only Anthropic models stream tool calls, using content item type tool_use.
    return [
        content_item
        for content_item in content
        if isinstance(content_item, str) or content_item["type"] != "tool_use"
    ]

    
async def _process_stream_event(event: StreamEvent, user_input: StreamInput, run_id: str) -> AsyncGenerator[str, None]:
    """Helper to process stream events consistently"""
    if not event:
        return
    
    # Handle messages after node execution
    if (
        event["event"] == "on_chain_end"
        and any(t.startswith("graph:step:") for t in event.get("tags", []))
        and event["data"].get("output") is not None
        and "messages" in event["data"]["output"]
        and event["metadata"].get("langgraph_node", "") not in ["human_review", "summarize_conversation"]
    ):
        new_messages = event["data"]["output"]["messages"]
        if not isinstance(new_messages, list):
            new_messages = [new_messages]

        # This is a proper hacky way to make sure that no messages are sent from the retreiaval decider node
        if event["metadata"].get("langgraph_node", "") == "retrieval_decider":
            print(f"Retrieval decider node returned text content, erasing...")
            erase_content = True
        else:
            erase_content = False
            
        for message in new_messages:
            if erase_content:
                message.content = ""
            try:
                chat_message = ChatMessage.from_langchain(message)
                chat_message.run_id = str(run_id)
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Error parsing message: {e}'})}\n\n"
                continue
            
            # We need this first if statement to avoid returning the user input, which langchain does for some reason
            if not (chat_message.type == "human" and chat_message.content == user_input.message):
                chat_message.pretty_print()

                if chat_message.type == "tool":
                    # Get rid of the original langchain message as it often breaks the JSON
                    # and we don't need it anyway
                    chat_message.original = None

                    tool_message_dict = {'type': 'tool', 'content': chat_message.model_dump()}
                    yield f"data: {json.dumps(tool_message_dict)}\n\n"
                
                else:
                    yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

    # Handle tokens streamed from LLMs
    if (
        event["event"] == "on_chat_model_stream"
        and user_input.stream_tokens
        and event['metadata'].get('langgraph_node', '') != "transform_query"
        and event['metadata'].get('langgraph_node', '') != "retrieval_decider"
        and event['metadata'].get('langgraph_node', '') != "summarize_conversation"
    ):
        content = _remove_tool_calls(event["data"]["chunk"].content)
        if content:
            yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"
