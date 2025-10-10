import json
import uuid
import os
import logging

from typing import List, Optional

from pprint import pprint

from langchain_openai.chat_models import ChatOpenAI
from langchain_anthropic.chat_models import ChatAnthropic
from langchain_core.messages import ToolMessage, SystemMessage, RemoveMessage, AIMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
#from langchain_community.callbacks import get_openai_callback, get_bedrock_anthropic_callback

from agent.components.retrieval.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.retrieval.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph
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

# NOTE: Opey node gets built in graph_builder

async def return_message(state: OpeyGraphState):
    """
    This dummy function is used as a node so that we can route to the message summary node in case that Opey
    """
    pass


async def human_review_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Enhanced human review node with dynamic interrupt and ApprovalManager.
    
    This node:
    1. Checks if tool calls have pre-existing approvals (session/user/workspace)
    2. If not approved, uses interrupt() to pause and request approval
    3. Processes approval decision and updates state
    4. Only interrupts when actually needed (not on every call)
    
    Args:
        state: The graph state
        config: RunnableConfig containing 'approval_manager' in configurable section
    """
    logger.info("Entering human review node")
    
    # Import here to avoid circular dependency
    from agent.components.tools import get_tool_registry
    
    messages = state["messages"]
    if not messages:
        logger.warning("No messages in state")
        return state
    
    tool_call_message = messages[-1]
    if not (hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls):
        logger.warning("No tool calls found in latest message")
        return state
    
    tool_registry = get_tool_registry()
    
    # Get approval_manager from config (LangGraph's recommended pattern)
    configurable = config.get("configurable", {}) if config else {}
    approval_manager = configurable.get("approval_manager")
    
    if not approval_manager:
        logger.warning("No approval_manager in config, approval system not configured")
        # Fallback: use basic interrupt without approval checking
        return state
    
    # Track which tool calls need approval
    pending_approvals = []
    approved_tool_calls = []
    
    for tool_call in tool_call_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        
        # Determine the "operation" key for this tool
        # For obp_requests, it's the HTTP method
        operation = tool_args.get("method", "execute").upper()
        
        # Check if this tool call requires approval
        if not tool_registry.should_require_approval(tool_name, tool_args):
            logger.info(f"Tool call auto-approved by pattern: {tool_name}")
            approved_tool_calls.append(tool_call["id"])
            continue
        
        # Check multi-level approval (session/user/workspace)
        approval_status = await approval_manager.check_approval(
            state=state,
            tool_name=tool_name,
            operation=operation,
            config={}  # Will be injected by graph runtime
        )
        
        if approval_status == "approved":
            logger.info(f"Tool call pre-approved from persistence: {tool_name} {operation}")
            approved_tool_calls.append(tool_call["id"])
            continue
        elif approval_status == "denied":
            logger.info(f"Tool call pre-denied from persistence: {tool_name} {operation}")
            # Inject denial message immediately
            state["messages"].append(ToolMessage(
                content=f"This operation was previously denied: {tool_name} {operation}",
                tool_call_id=tool_call["id"]
            ))
            continue
        
        # Needs approval - build rich context
        session_history = {
            "similar_count": _count_similar_operations(state, tool_name, operation),
            "last_similar_approval": _get_last_approval_time(state, tool_name, operation)
        }
        
        approval_context = tool_registry.build_approval_context(
            tool_name=tool_name,
            tool_call_id=tool_call["id"],
            tool_args=tool_args,
            session_history=session_history
        )
        
        pending_approvals.append(approval_context)
    
    # If all tool calls are already approved/denied, no need to interrupt
    if not pending_approvals:
        logger.info("All tool calls pre-approved or denied, continuing without interrupt")
        return state
    
    # Now we need approval - use LangGraph's interrupt()
    logger.info(f"Requesting approval for {len(pending_approvals)} tool call(s)")
    
    # For single tool call approval
    if len(pending_approvals) == 1:
        approval_context = pending_approvals[0]
        
        # Use interrupt() to pause execution
        # NOTE: interrupt() raises a NodeInterrupt exception, it does NOT return a value
        # The graph will pause here, and when resumed with Command(resume=user_response),
        # the interrupt() call will return that user_response value
        logger.info(f"Calling interrupt() for tool: {approval_context.tool_name}")
        user_response = interrupt(approval_context.model_dump())
        logger.info(f"Interrupt returned with user response: {user_response}")
        
        # This code only runs after the graph is resumed with user input
        approved = user_response.get("approved", False)
        approval_level = user_response.get("approval_level", "once")
        
        if approved:
            logger.info(f"User approved tool call: {approval_context.tool_call_id}")
            
            # Save approval at specified level
            from agent.components.tools.approval_models import ApprovalDecision, ApprovalLevel
            decision = ApprovalDecision(
                approved=True,
                approval_level=ApprovalLevel(approval_level)
            )
            
            await approval_manager.save_approval(
                state=state,
                tool_name=approval_context.tool_name,
                operation=approval_context.tool_input.get("method", "execute").upper(),
                decision=decision,
                config={}
            )
        else:
            logger.info(f"User denied tool call: {approval_context.tool_call_id}")
            
            # Inject denial message
            state["messages"].append(ToolMessage(
                content=f"User denied request: {user_response.get('feedback', 'Operation not approved')}",
                tool_call_id=approval_context.tool_call_id
            ))
    
    # For batch approval (multiple tool calls)
    else:
        batch_payload = {
            "approval_type": "batch",
            "tool_calls": [ctx.model_dump() for ctx in pending_approvals],
            "options": ["approve_all", "deny_all", "approve_selected"]
        }
        
        logger.info(f"Calling interrupt() for batch approval of {len(pending_approvals)} tools")
        user_response = interrupt(batch_payload)
        logger.info(f"Batch interrupt returned with user response: {user_response}")
        
        # This code only runs after the graph is resumed
        action = user_response.get("action", "deny_all")
        
        if action == "approve_all":
            for approval_context in pending_approvals:
                # Save approvals
                from agent.components.tools.approval_models import ApprovalDecision, ApprovalLevel
                decision = ApprovalDecision(
                    approved=True,
                    approval_level=ApprovalLevel(user_response.get("approval_level", "once"))
                )
                await approval_manager.save_approval(
                    state=state,
                    tool_name=approval_context.tool_name,
                    operation=approval_context.tool_input.get("method", "execute").upper(),
                    decision=decision,
                    config={}
                )
        
        elif action == "approve_selected":
            approved_ids = user_response.get("approved_ids", [])
            for approval_context in pending_approvals:
                if approval_context.tool_call_id in approved_ids:
                    # Approve
                    from agent.components.tools.approval_models import ApprovalDecision, ApprovalLevel
                    decision = ApprovalDecision(
                        approved=True,
                        approval_level=ApprovalLevel.ONCE
                    )
                    await approval_manager.save_approval(
                        state=state,
                        tool_name=approval_context.tool_name,
                        operation=approval_context.tool_input.get("method", "execute").upper(),
                        decision=decision,
                        config={}
                    )
                else:
                    # Deny
                    state["messages"].append(ToolMessage(
                        content="User denied this operation in batch approval",
                        tool_call_id=approval_context.tool_call_id
                    ))
        
        else:  # deny_all
            for approval_context in pending_approvals:
                state["messages"].append(ToolMessage(
                    content="User denied all operations in batch",
                    tool_call_id=approval_context.tool_call_id
                ))
    
    return state


def _count_similar_operations(state: OpeyGraphState, tool_name: str, operation: str) -> int:
    """Count similar operations in session history"""
    count = 0
    session_approvals = state.get("session_approvals", {})
    for key in session_approvals:
        if key[0] == tool_name and key[1] == operation:
            count += 1
    return count


def _get_last_approval_time(state: OpeyGraphState, tool_name: str, operation: str) -> Optional[str]:
    """Get timestamp of last similar approval"""
    approval_timestamps = state.get("approval_timestamps", {})
    key = (tool_name, operation)
    timestamp = approval_timestamps.get(key)
    return timestamp.isoformat() if timestamp else None
