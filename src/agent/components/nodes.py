import json
import uuid
import os
import logging

from typing import List

from pprint import pprint

from langchain_openai.chat_models import ChatOpenAI
from langchain_anthropic.chat_models import ChatAnthropic
from langchain_core.messages import ToolMessage, SystemMessage, RemoveMessage, AIMessage, trim_messages
#from langchain_community.callbacks import get_openai_callback, get_bedrock_anthropic_callback

from agent.components.chains import opey_agent, query_formulator_chain
from agent.components.sub_graphs.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.sub_graphs.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph
from agent.components.states import OpeyGraphState
from agent.components.chains import conversation_summarizer_chain
from agent.utils.model_factory import get_llm

logger = logging.getLogger("uvicorn.error")

async def run_summary_chain(state: OpeyGraphState):
    logger.info("----- SUMMARIZING CONVERSATION -----")
    state["current_state"] = "summarize_conversation"
    total_tokens = state["total_tokens"]
    if not total_tokens:
        raise ValueError("Total tokens not found in state")
    
    summary = state.get("conversation_summary", "")
    if summary:
        summary_system_message = f"""This is a summary of the conversation so far:\n {summary}\n
        Extend this summary by taking into account the new messages below"""
    else:
        summary_system_message = ""



    messages = state["messages"]

    # After we summarize we reset the token_count to zero, this will be updated when Opey is next called
    summary = await conversation_summarizer_chain.ainvoke({"messages": messages, "existing_summary_message": summary_system_message})

    logger.debug(f"\nSummary: {summary}\n")

    # Right now we delete all but the last two messages
    trimmed_messages = trim_messages(
        messages=messages,
        token_counter=get_llm("medium"),
        max_tokens=4000,
        strategy="last",
        include_system=True
    )

    # We need to verify that all tool messages in the trimmed messages are preceded by an AI message with a tool call
    to_insert: List[tuple] = []
    for i, trimmed_messages_msg in enumerate(trimmed_messages):
        # Stop at each ToolMessage to find the AIMessage that called it
        if isinstance(trimmed_messages_msg, ToolMessage):
            print(f"Checking tool message {trimmed_messages_msg}")
            tool_call_id = trimmed_messages_msg.tool_call_id
            found_tool_call = False
            for k, msg in enumerate(messages):
                # Find the AIMessage that called the tool
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    # Check if a tool call with the same tool_call_id as our ToolMessage is in the tool calls of the AIMessage
                    if tool_call_id in [tool_call["id"] for tool_call in msg.tool_calls]:
                        # Insert the AIMessage before the ToolMessage in the trimmed messages, the insert method inserts element before the index
                        to_insert.append((i, msg))
                        found_tool_call = True
                        break
            if not found_tool_call:
                raise Exception(f"Could not find tool call for ToolMessage {trimmed_messages_msg} with id {trimmed_messages_msg.id} in the messages")

    # Insert the AIMessages before the ToolMessages in trimmed_messages
    if to_insert:
        for pair in to_insert:
            i, msg = pair
            trimmed_messages.insert(i, msg)

    print(f"\nTrimmed messages:\n")
    for msg in trimmed_messages:
        msg.pretty_print()
    delete_messages = [RemoveMessage(id=message.id) for message in messages if message not in trimmed_messages]

    # Reset total tokens count, this is fine to do even though messages remain in the state as the tokens are counted 
    # at the run of the Opey node
    total_tokens = 0

    return {"messages": delete_messages, "conversation_summary": summary, "total_tokens": total_tokens}
    
async def run_opey(state: OpeyGraphState):

    # Check if we have a convesration summary
    summary = state.get("conversation_summary", "")
    if summary:
        summary_system_message = f"Summary of earlier conversation: {summary}"
        messages = [SystemMessage(content=summary_system_message)] + state["messages"]
    else:
        messages = state["messages"]

    response = await opey_agent.ainvoke({"messages": messages})

    # Count the tokens in the messages
    total_tokens = state.get("total_tokens", 0)
    llm = get_llm("medium")

    try:
        total_tokens += llm.get_num_tokens_from_messages(messages)
    except NotImplementedError as e:
        # Note that this defaulting to gpt-4o wont work if there is no OpenAI API key in the env, so will probably need to find another defaulting method
        print(f"could not count tokens for model provider {os.getenv('MODEL_PROVIDER')}:\n{e}\n\ndefaulting to OpenAI GPT-4o counting...")
        total_tokens += ChatOpenAI(model='gpt-4o').get_num_tokens_from_messages(messages)

    return {"messages": response, "total_tokens": total_tokens}

async def return_message(state: OpeyGraphState):
    """
    This dummy function is used as a node so that we can route to the message summary node in case that Opey 
    """
    pass

async def human_review_node(state):
    state["current_state"] = "human_review"
    print("Awaiting human approval for tool call...")
    pass
