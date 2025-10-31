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


# ============================================================================
# Human Review Node - Helper Functions
# ============================================================================

def _extract_operation(tool_name: str, tool_args: Dict) -> str:
    """
    Extract operation identifier from tool args.
    
    For obp_requests tool, prioritizes operation_id if available,
    otherwise falls back to method:path.
    For other tools, uses generic descriptors or returns the tool name.
    
    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool
        
    Returns:
        str: Operation identifier for approval keying
    """
    # OBP requests tool - use operation_id if available
    if tool_name == "obp_requests":
        if "operation_id" in tool_args and tool_args["operation_id"]:
            return tool_args["operation_id"]
        elif "method" in tool_args and "path" in tool_args:
            # Fallback for when operation_id isn't available
            return f"{tool_args['method']}:{tool_args['path']}"
        return "unknown_operation"
    
    # For other tools, try to extract a meaningful operation identifier
    # This makes the system more generic and not API-specific
    if "operation" in tool_args:
        return tool_args["operation"]
    
    if "action" in tool_args:
        return tool_args["action"]
    
    # Fallback: use the tool name itself as the operation
    # This means approval is per-tool rather than per-operation
    return tool_name


def _build_session_history(
    state: OpeyGraphState, 
    tool_name: str, 
    operation: str
) -> Dict:
    """Build session history for approval context"""
    from agent.components.states import make_approval_key
    
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


async def _categorize_tool_calls(
    tool_calls: List,
    approval_manager,
    tool_registry,
    state: OpeyGraphState
) -> tuple[List, List, List]:
    """
    Categorize tool calls into auto-approved, denied, and needs-approval.
    
    Returns:
        tuple: (auto_approved, denied, needs_approval) lists of tool calls
    """
    auto_approved = []
    denied = []
    needs_approval = []
    
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]
        operation = _extract_operation(tool_name, tool_args)
        
        # Check existing approvals
        approval_status = await approval_manager.check_approval(
            state=state,
            tool_name=tool_name,
            operation=operation,
            config={}
        )
        
        if approval_status == "approved":
            logger.info(f"Tool call pre-approved: {tool_name} ({tool_call_id})")
            auto_approved.append(tool_call)
            continue
        
        if approval_status == "denied":
            logger.warning(f"Tool call pre-denied: {tool_name} ({tool_call_id})")
            denied.append(tool_call)
            continue
        
        # Check if tool requires approval
        if not tool_registry.should_require_approval(tool_name, tool_args):
            logger.info(f"Tool {tool_name} auto-approved by pattern ({tool_call_id})")
            auto_approved.append(tool_call)
            continue
        
        # Needs user approval
        needs_approval.append(tool_call)
    
    return auto_approved, denied, needs_approval


def _build_approval_contexts(
    tool_calls: List,
    tool_registry,
    state: OpeyGraphState
) -> List[Dict]:
    """
    Build approval contexts for all tool calls requiring approval.
    
    Args:
        tool_calls: List of tool calls needing approval
        tool_registry: Tool registry for building contexts
        state: Current graph state
        
    Returns:
        List of approval context dictionaries
    """
    approval_contexts = []
    
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]
        operation = _extract_operation(tool_name, tool_args)
        
        session_history = _build_session_history(state, tool_name, operation)
        approval_context = tool_registry.build_approval_context(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            session_history=session_history
        )
        approval_contexts.append(approval_context.model_dump())
    
    return approval_contexts


def _create_interrupt_payload(
    needs_approval: List,
    approval_contexts: List[Dict]
) -> tuple[Dict, bool]:
    """
    Create the interrupt payload based on number of approvals needed.
    
    Args:
        needs_approval: List of tool calls needing approval
        approval_contexts: List of approval context dicts
        
    Returns:
        tuple: (payload, is_batch)
    """
    if len(needs_approval) == 1:
        # Single approval (backward compatible)
        logger.info(f"Creating single approval request for tool: {needs_approval[0]['name']}")
        return approval_contexts[0], False
    else:
        # Batch approval
        logger.info(f"Creating batch approval request for {len(needs_approval)} tools")
        return {
            "approval_type": "batch",
            "tool_calls": approval_contexts,
            "options": ["approve_all", "deny_all", "approve_selected"]
        }, True


async def _process_batch_approval_response(
    user_response: Dict,
    needs_approval: List,
    approval_manager,
    state: OpeyGraphState
) -> tuple[Dict, Dict, List]:
    """
    Process batch approval response from user.
    
    Args:
        user_response: User's batch approval decisions
        needs_approval: List of tool calls that needed approval
        approval_manager: Approval manager instance
        state: Current graph state
        
    Returns:
        tuple: (updated_session_approvals, updated_approval_timestamps, tool_messages)
    """
    from agent.components.states import make_approval_key
    
    updated_session_approvals = state.get("session_approvals", {}).copy()
    updated_approval_timestamps = state.get("approval_timestamps", {}).copy()
    tool_messages = []
    
    logger.info(f"Processing batch approval response with {len(user_response.get('decisions', {}))} decisions")
    
    decisions = user_response.get("decisions", {})
    
    for tool_call in needs_approval:
        tool_call_id = tool_call["id"]
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        operation = _extract_operation(tool_name, tool_args)
        
        decision = decisions.get(tool_call_id)
        if not decision:
            logger.warning(f"No decision found for tool_call_id: {tool_call_id}, defaulting to deny")
            tool_messages.append(ToolMessage(
                content=f"Tool call denied - no decision provided",
                tool_call_id=tool_call_id
            ))
            continue
        
        if decision.get("approved"):
            approval_level = decision.get("approval_level", "once")
            logger.info(f"User approved: {tool_call_id} at level: {approval_level}")
            
            # Save approval
            try:
                approval_level_enum = ApprovalLevel(approval_level)
            except ValueError:
                logger.warning(f"Invalid approval level '{approval_level}', defaulting to 'once'")
                approval_level_enum = ApprovalLevel.ONCE
            
            approval_decision = ApprovalDecision(
                approved=True,
                approval_level=approval_level_enum,
            )
            
            await approval_manager.save_approval(
                state=state,
                tool_name=tool_name,
                operation=operation,
                decision=approval_decision,
                config={}
            )
            
            # Update session state if needed
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
    
    return updated_session_approvals, updated_approval_timestamps, tool_messages


async def _process_single_approval_response(
    user_response: Dict,
    tool_call: Dict,
    approval_manager,
    state: OpeyGraphState
) -> tuple[Dict, Dict, List]:
    """
    Process single approval response from user.
    
    Args:
        user_response: User's approval decision
        tool_call: The tool call that needed approval
        approval_manager: Approval manager instance
        state: Current graph state
        
    Returns:
        tuple: (updated_session_approvals, updated_approval_timestamps, tool_messages)
    """
    from agent.components.states import make_approval_key
    
    updated_session_approvals = state.get("session_approvals", {}).copy()
    updated_approval_timestamps = state.get("approval_timestamps", {}).copy()
    tool_messages = []
    
    tool_call_id = tool_call["id"]
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    operation = _extract_operation(tool_name, tool_args)
    
    if user_response.get("approved"):
        approval_level = user_response.get("approval_level", "once")
        logger.info(f"User approved: {tool_call_id} at level: {approval_level}")
        
        try:
            approval_level_enum = ApprovalLevel(approval_level)
        except ValueError:
            logger.warning(f"Invalid approval level '{approval_level}', defaulting to 'once'")
            approval_level_enum = ApprovalLevel.ONCE
        
        decision = ApprovalDecision(
            approved=True,
            approval_level=approval_level_enum,
        )
        
        await approval_manager.save_approval(
            state=state,
            tool_name=tool_name,
            operation=operation,
            decision=decision,
            config={}
        )
        
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
    
    return updated_session_approvals, updated_approval_timestamps, tool_messages


# ============================================================================
# Main Human Review Node
# ============================================================================


async def human_review_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Enhanced human review node with batch approval support.
    
    Collects ALL tool calls requiring approval and requests approval in a single
    interrupt() call to avoid race conditions with parallel tool calls.
    
    Workflow:
    1. Categorize tool calls (auto-approved, denied, needs approval)
    2. Create denial messages for pre-denied tools
    3. Build approval contexts for tools needing approval
    4. Call interrupt() ONCE with single or batch payload
    5. Process user response and save approvals
    
    Args:
        state: Graph state containing messages and approval history
        config: RunnableConfig with 'approval_manager' in configurable section
        
    Returns:
        State updates with tool messages and approval records
    """
    logger.info("Entering human review node")
    
    from agent.components.tools import get_tool_registry
    
    # Validate state
    messages = state["messages"]
    if not messages:
        logger.warning("No messages in state")
        return {}
    
    tool_call_message = messages[-1]
    if not (hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls):
        logger.warning("No tool calls found in last message")
        return {}
    
    # Get dependencies
    tool_registry = get_tool_registry()
    configurable = config.get("configurable", {}) if config else {}
    approval_manager: ApprovalManager | None = configurable.get("approval_manager")
    
    if not approval_manager:
        logger.error("No approval_manager in config")
        return {}
    
    tool_calls = tool_call_message.tool_calls
    logger.info(f"Processing {len(tool_calls)} tool call(s)")
    
    # Step 1: Categorize all tool calls
    auto_approved, denied, needs_approval = await _categorize_tool_calls(
        tool_calls=tool_calls,
        approval_manager=approval_manager,
        tool_registry=tool_registry,
        state=state
    )
    
    # Step 2: Handle denied tools - create error messages
    tool_messages = []
    for tool_call in denied:
        tool_messages.append(ToolMessage(
            content=f"Tool call denied by approval policy",
            tool_call_id=tool_call["id"]
        ))
    
    # Step 3: If no tools need approval, we're done
    if not needs_approval:
        logger.info(f"No tools require approval. Auto-approved: {len(auto_approved)}, Denied: {len(denied)}")
        return {"messages": tool_messages} if tool_messages else {}
    
    # Step 4: Build approval contexts for all pending tools
    approval_contexts = _build_approval_contexts(
        tool_calls=needs_approval,
        tool_registry=tool_registry,
        state=state
    )
    
    # Step 5: Create interrupt payload (single or batch)
    interrupt_payload, is_batch = _create_interrupt_payload(
        needs_approval=needs_approval,
        approval_contexts=approval_contexts
    )
    
    # Step 6: Call interrupt() ONCE - graph suspends after this node completes
    logger.info(f"Calling interrupt() for {'batch' if is_batch else 'single'} approval")
    user_response = interrupt(interrupt_payload)
    
    # === CODE BELOW ONLY RUNS AFTER GRAPH RESUMPTION ===
    logger.info(f"Graph resumed with approval decision(s)")
    
    # Step 7: Process user response based on format
    if isinstance(user_response, dict) and "decisions" in user_response:
        # Batch response
        (updated_session_approvals, 
         updated_approval_timestamps, 
         approval_tool_messages) = await _process_batch_approval_response(
            user_response=user_response,
            needs_approval=needs_approval,
            approval_manager=approval_manager,
            state=state
        )
        tool_messages.extend(approval_tool_messages)
    else:
        # Single approval response (backward compatible)
        if len(needs_approval) != 1:
            logger.error(f"Expected single approval but got {len(needs_approval)} tool calls")
            return {"messages": tool_messages} if tool_messages else {}
        
        (updated_session_approvals, 
         updated_approval_timestamps, 
         approval_tool_messages) = await _process_single_approval_response(
            user_response=user_response,
            tool_call=needs_approval[0],
            approval_manager=approval_manager,
            state=state
        )
        tool_messages.extend(approval_tool_messages)
    
    # Step 8: Return state updates
    logger.info(f"Returning with {len(tool_messages)} tool message(s)")
    return {
        "messages": tool_messages,
        "session_approvals": updated_session_approvals,
        "approval_timestamps": updated_approval_timestamps
    }
    
async def sanitize_tool_responses(state: OpeyGraphState, config: RunnableConfig):
    """
    Sanitize tool responses in case they contain too much data. I.e. too many tokens.
    
    Args:
        state: Graph state containing messages
        config: RunnableConfig (not used here)
    """
    
    from agent.utils.token_counter import count_tokens, count_tokens_from_messages
    from agent.utils.model_factory import get_max_input_tokens
    
    messages = state["messages"]
    if not messages:
        return {}
    
    if not isinstance(messages[-1], ToolMessage):
        logger.warning("Last message is not a ToolMessage")
        return {}
    
    # Extract model configuration from RunnableConfig
    configurable = config.get("configurable", {}) if config else {}
    model_name = configurable.get("model_name")
    model_kwargs = configurable.get("model_kwargs", {})
    
    if not model_name:
        logger.error("No model_name in config for token counting")
        return {}
    
    # Check if total messages exceed token limit
    total_tokens = count_tokens_from_messages(
        messages=messages,
        model_name=model_name,
        model_kwargs=model_kwargs
    )
    
    max_input_tokens = get_max_input_tokens(model_name)
    
    logger.info(f"Total tokens in messages: {total_tokens}, Max input tokens for model '{model_name}': {max_input_tokens}")
    if total_tokens <= max_input_tokens:
        logger.info("No sanitization needed, token count within limits")
        return {}
    
    # Sanitize the last ToolMessage's content
    tool_message: ToolMessage = messages[-1]
    original_content = tool_message.content
    sanitized_content = original_content[:1000] + "\n\n[TRUNCATED TOOL RESPONSE DUE TO EXCESSIVE LENGTH]"
    
    tool_message.content = sanitized_content
    logger.info("Sanitized ToolMessage content due to excessive token count")
    return {"messages": [tool_message]}
    
    
    
    
    
    

