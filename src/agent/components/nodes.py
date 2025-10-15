import json
import uuid
import os
import logging
import datetime

from typing import List, Dict

from pprint import pprint

from langchain_openai.chat_models import ChatOpenAI
from langchain_anthropic.chat_models import ChatAnthropic
from langchain_core.messages import ToolMessage, SystemMessage, RemoveMessage, AIMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
#from langchain_community.callbacks import get_openai_callback, get_bedrock_anthropic_callback

from agent.components.retrieval.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.retrieval.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph
from agent.components.states import OpeyGraphState, make_approval_key
from agent.components.chains import conversation_summarizer_chain
from agent.components.tools import ApprovalManager
from agent.components.tools.approval_models import ApprovalLevel, ApprovalDecision
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

# NOTE: Opey node gets built in graph_builder

async def return_message(state: OpeyGraphState):
    """
    This dummy function is used as a node so that we can route to the message summary node in case that Opey
    """
    pass


async def human_review_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Enhanced human review node with dynamic interrupt and ApprovalManager.
    
    Handles tool call approval workflow:
    1. Checks for pre-existing approvals (session/user/workspace levels)
    2. For unapproved calls, uses interrupt() to request human approval
    3. Processes approval decision and persists based on approval level
    
    Args:
        state: Graph state containing messages and approval history
        config: RunnableConfig with 'approval_manager' in configurable section
    """
    logger.info("Entering human review node")
    
    from agent.components.tools import get_tool_registry
    
    messages = state["messages"]
    if not messages:
        logger.warning("No messages in state")
        return {}
    
    tool_call_message = messages[-1]
    if not (hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls):
        logger.warning("No tool calls found in last message")
        return {}
    
    tool_registry = get_tool_registry()
    
    configurable = config.get("configurable", {}) if config else {}
    approval_manager: ApprovalManager | None = configurable.get("approval_manager")
    
    if not approval_manager:
        logger.error("No approval_manager in config")
        return {}
    
    tool_calls = tool_call_message.tool_calls
    logger.info(f"Requesting approval for {len(tool_calls)} tool call(s)")
    
    tool_messages = []
    updated_session_approvals = state.get("session_approvals", {}).copy()
    updated_approval_timestamps = state.get("approval_timestamps", {}).copy()
    interrupted = False  # Track if we called interrupt()
    
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]
        operation = _extract_operation(tool_args)
        
        # Check if approval already exists at any level
        approval_status = await approval_manager.check_approval(
            state=state,
            tool_name=tool_name,
            operation=operation,
            config={}
        )
        
        if approval_status == "approved":
            logger.info(f"Tool call pre-approved: {tool_name}")
            continue
        
        if approval_status == "denied":
            logger.warning(f"Tool call denied: {tool_name}")
            tool_messages.append(ToolMessage(
                content=f"Tool call denied by approval policy",
                tool_call_id=tool_call_id
            ))
            continue
        
        # Check if tool requires approval
        if not tool_registry.should_require_approval(tool_name, tool_args):
            logger.info(f"Tool {tool_name} auto-approved by pattern")
            continue
        
        # Build rich approval context
        session_history = _build_session_history(state, tool_name, operation)
        approval_context = tool_registry.build_approval_context(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            session_history=session_history
        )
        
        logger.info(f"Calling interrupt() for tool: {tool_name}")
        logger.info(f"Interrupt will suspend graph execution until Command(resume=...) is provided")
        
        # Interrupt execution and wait for human decision
        # After calling interrupt(), the node MUST complete (not return early)
        # The graph will suspend AFTER this node completes
        # On resumption with Command(resume=...), this node runs AGAIN from the start
        # But this time interrupt() returns the resume value instead of suspending
        user_response = interrupt(approval_context.model_dump())
        interrupted = True
        
        # === CODE BELOW ONLY RUNS AFTER GRAPH RESUMPTION ===
        logger.info(f"Graph resumed with approval decision: {user_response}")
        
        if user_response.get("approved"):
            approval_level = user_response.get("approval_level", "once")
            logger.info(f"User approved: {tool_call_id} at level: {approval_level}")
            
            # Convert string to enum
            try:
                approval_level_enum = ApprovalLevel(approval_level)
            except ValueError:
                logger.warning(f"Invalid approval level '{approval_level}', defaulting to 'once'")
                approval_level_enum = ApprovalLevel.ONCE
            
            # TODO: Allow modified args in the future
            decision = ApprovalDecision(
                approved=True,
                approval_level=approval_level_enum,
                #modified_args=None,
            )
            
            # Save approval record
            await approval_manager.save_approval(
                state=state,
                tool_name=tool_name,
                operation=operation,
                decision=decision,
                config={}
            )
            
            # Update session state if session-level approval
            if approval_level_enum == ApprovalLevel.SESSION:
                approval_key = make_approval_key(tool_name, operation)
                updated_session_approvals[approval_key] = True
                updated_approval_timestamps[approval_key] = datetime.datetime.now()
        else:
            logger.info(f"User denied: {tool_call_id}")
            tool_messages.append(ToolMessage(
                content=f"Tool call denied by user",
                tool_call_id=tool_call_id
            ))
    
    # Return state updates
    # CRITICAL: If we called interrupt(), the graph will suspend AFTER this return
    # This return is for when we resume or when no interrupt was needed
    if interrupted:
        logger.info(f"human_review_node completed AFTER interrupt - graph will now suspend")
    else:
        logger.info(f"human_review_node completed without interrupt - proceeding to next node")
    
    logger.info(f"Returning with {len(tool_messages)} tool message(s)")
    return {
        "messages": tool_messages,
        "session_approvals": updated_session_approvals,
        "approval_timestamps": updated_approval_timestamps
    }


def _extract_operation(tool_args: Dict) -> str:
    """Extract operation identifier from tool args"""
    if "method" in tool_args and "path" in tool_args:
        return f"{tool_args['method']}:{tool_args['path']}"
    return "unknown"


def _build_session_history(
    state: OpeyGraphState, 
    tool_name: str, 
    operation: str
) -> Dict:
    """Build session history for approval context"""
    approvals = state.get("session_approvals", {})
    timestamps = state.get("approval_timestamps", {})
    
    approval_key = make_approval_key(tool_name, operation)
    
    # Count similar approved operations
    similar_count = sum(1 for k in approvals.keys() if k == approval_key)
    
    # Get last approval time
    last_approval_time = timestamps.get(approval_key)
    
    return {
        "similar_count": similar_count,
        "last_similar_approval": last_approval_time
    }
