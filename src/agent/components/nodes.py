import json
import uuid
import os
import logging

from typing import List, Dict

from pprint import pprint

from langchain_openai.chat_models import ChatOpenAI
from langchain_anthropic.chat_models import ChatAnthropic
from langchain_core.messages import ToolMessage, SystemMessage, RemoveMessage, AIMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent.components.states import OpeyGraphState
from agent.components.chains import conversation_summarizer_chain
from agent.components.tools import ApprovalStore, ApprovalScope, ApprovalRequest
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
# Human Review Node - Simplified Approval System
# ============================================================================


def _build_approval_requests(tool_calls: List[Dict]) -> List[ApprovalRequest]:
    """Build approval request objects for tool calls."""
    return [
        ApprovalRequest(
            tool_name=tc["name"],
            tool_call_id=tc["id"],
            tool_args=tc["args"],
            description=tc.get("description"),
        )
        for tc in tool_calls
    ]


def _create_interrupt_payload(requests: List[ApprovalRequest]) -> Dict:
    """
    Create interrupt payload for approval UI.
    
    Supports both single and batch approval in one format.
    """
    tool_calls = [
        {
            "tool_call_id": req.tool_call_id,
            "tool_name": req.tool_name,
            "tool_args": req.tool_args,
            "description": req.description,
        }
        for req in requests
    ]
    
    return {
        "approval_type": "batch" if len(requests) > 1 else "single",
        "tool_calls": tool_calls,
        "available_scopes": [s.value for s in ApprovalScope],
    }


def _process_approval_response(
    user_response: Dict,
    requests: List[ApprovalRequest],
    approval_store: ApprovalStore,
) -> tuple[List[str], List[ToolMessage]]:
    """
    Process user's approval decisions.
    
    Args:
        user_response: User decisions from interrupt
        requests: Original approval requests
        approval_store: Store to persist approvals
        
    Returns:
        tuple: (approved_tool_ids, denial_messages)
    """
    approved_ids = []
    denial_messages = []
    
    # Handle different response formats
    decisions = user_response.get("decisions", {})
    
    # If no decisions dict, treat as single approval format
    if not decisions and len(requests) == 1:
        req = requests[0]
        decisions = {req.tool_call_id: user_response}
    
    for req in requests:
        decision = decisions.get(req.tool_call_id)
        
        if not decision:
            # No decision = denied
            logger.warning(f"No decision for {req.tool_call_id}, treating as denied")
            denial_messages.append(ToolMessage(
                content="Tool call denied - no decision provided",
                tool_call_id=req.tool_call_id,
                status="error"
            ))
            continue
        
        if decision.get("approved"):
            # Grant approval at chosen scope
            scope_str = decision.get("scope", "once")
            try:
                scope = ApprovalScope(scope_str)
            except ValueError:
                scope = ApprovalScope.ONCE
            
            approval_store.grant(req.tool_name, scope)
            approved_ids.append(req.tool_call_id)
            logger.info(f"Approved {req.tool_name} at scope {scope.value}")
        else:
            denial_messages.append(ToolMessage(
                content=f"Tool call denied by user",
                tool_call_id=req.tool_call_id,
                status="error"
            ))
            logger.info(f"User denied {req.tool_name}")
    
    return approved_ids, denial_messages


async def human_review_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Human review node with simplified approval system.
    
    Logic:
    1. Check which tools need approval (not already approved)
    2. If all approved, pass through
    3. Otherwise, interrupt for user decision
    4. Process response and update approval store
    
    Args:
        state: Graph state with messages
        config: Must contain 'approval_store' in configurable
        
    Returns:
        State updates with denial messages (if any)
    """
    logger.info("Entering human review node")
    
    messages = state["messages"]
    if not messages:
        return {}
    
    tool_call_message = messages[-1]
    if not (hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls):
        return {}
    
    # Get approval store from config
    configurable = config.get("configurable", {}) if config else {}
    approval_store: ApprovalStore | None = configurable.get("approval_store")
    
    if not approval_store:
        logger.error("No approval_store in config - allowing all tools")
        return {}
    
    tool_calls = tool_call_message.tool_calls
    logger.info(f"Checking {len(tool_calls)} tool call(s)")
    
    # Separate into already-approved and needs-approval
    needs_approval = []
    for tc in tool_calls:
        if not approval_store.is_approved(tc["name"]):
            needs_approval.append(tc)
        else:
            logger.debug(f"Tool {tc['name']} already approved")
    
    # If all tools are approved, pass through
    if not needs_approval:
        logger.info("All tools already approved")
        return {}
    
    # Build approval requests and interrupt
    requests = _build_approval_requests(needs_approval)
    payload = _create_interrupt_payload(requests)
    
    logger.info(f"Requesting approval for {len(requests)} tool(s)")
    user_response = interrupt(payload)
    
    # === After graph resume ===
    logger.info("Processing approval response")
    
    approved_ids, denial_messages = _process_approval_response(
        user_response=user_response,
        requests=requests,
        approval_store=approval_store,
    )
    
    # Update state with session approvals for persistence
    session_approvals = approval_store.get_session_approvals()
    
    result: Dict = {
        "session_approvals": session_approvals,
    }
    
    if denial_messages:
        result["messages"] = denial_messages
    
    return result
    
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


# ============================================================================
# Consent Check Node - Post-tool-execution consent handling
# ============================================================================


def _parse_consent_error(tool_message: ToolMessage) -> Dict | None:
    """
    Check if a ToolMessage contains a consent_required error from the MCP server.
    
    Returns parsed consent info dict or None if not a consent error.
    Expected MCP server error format:
        {"error": "consent_required", "required_roles": [...], "operation_id": "..."}
    """
    content = tool_message.content
    
    # Handle Anthropic-style content (list of content blocks)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and parsed.get("error") == "consent_required":
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    continue
        return None
    
    # Handle string content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None
    # Handle dict content
    elif isinstance(content, dict):
        parsed = content
    else:
        return None
    
    if isinstance(parsed, dict) and parsed.get("error") == "consent_required":
        return parsed
    return None


def _find_tool_call_for_message(messages: List, tool_call_id: str) -> Dict | None:
    """Find the original AIMessage tool call that produced a given tool_call_id."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("id") == tool_call_id:
                    return tc
    return None


async def consent_check_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Check tool responses for consent_required errors from MCP servers.
    
    When the MCP server's call_obp_api tool requires a Consent-JWT but none was
    provided, it returns a structured error. This node detects that error,
    interrupts to request a consent JWT from the frontend, then retries the 
    tool call with the JWT injected into the headers argument.
    
    Flow:
        1. Scan recent ToolMessages for consent_required errors
        2. If found → interrupt() with consent details
        3. Frontend obtains consent JWT from OBP and resumes
        4. Re-invoke the tool with Consent-JWT in headers
        5. Replace error ToolMessage with successful result
    """
    messages = state["messages"]
    if not messages:
        return {}
    
    # Find ToolMessages with consent_required errors
    consent_errors = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            consent_info = _parse_consent_error(msg)
            if consent_info:
                logger.info(f"🔐 CONSENT_FLOW: Detected consent_required error in tool message (tool_call_id={msg.tool_call_id})")
                consent_errors.append((msg, consent_info))
    
    if not consent_errors:
        logger.debug("🔐 CONSENT_FLOW: No consent errors found in messages, passing through")
        return {}
    
    # For now, handle the first consent error (could batch later)
    error_msg, consent_info = consent_errors[0]
    tool_call_id = error_msg.tool_call_id
    
    # Find the original tool call to get the tool name and args
    original_tc = _find_tool_call_for_message(messages, tool_call_id)
    if not original_tc:
        logger.error(f"Could not find original tool call for consent error (tool_call_id={tool_call_id})")
        return {}
    
    logger.info(f"🔐 CONSENT_FLOW: Consent required for tool '{original_tc['name']}', operation: {consent_info.get('operation_id')}")
    
    # Interrupt to request consent JWT from frontend
    consent_payload = {
        "consent_type": "consent_required",
        "tool_call_id": tool_call_id,
        "tool_name": original_tc["name"],
        "tool_args": original_tc.get("args", {}),
        "operation_id": consent_info.get("operation_id"),
        "required_roles": consent_info.get("required_roles", []),
    }
    
    logger.info(f"🔐 CONSENT_FLOW: Calling interrupt() with consent_payload (operation_id={consent_info.get('operation_id')})")
    user_response = interrupt(consent_payload)
    
    # ---- Resumed after frontend provides consent JWT ----
    
    logger.info(f"🔐 CONSENT_FLOW: Graph resumed after interrupt, user_response keys: {list(user_response.keys()) if isinstance(user_response, dict) else type(user_response)}")
    consent_jwt = user_response.get("consent_jwt")
    if not consent_jwt:
        logger.warning(f"🔐 CONSENT_FLOW: Consent response received without consent_jwt (user_response={user_response}) — treating as denied")
        denial_message = ToolMessage(
            content="Consent denied — no consent JWT provided",
            tool_call_id=tool_call_id,
            status="error",
        )
        return {"messages": [denial_message]}
    
    # Retry the tool call with Consent-JWT injected into headers arg
    jwt_preview = consent_jwt[:50] + "..." if len(consent_jwt) > 50 else consent_jwt
    logger.info(f"🔐 CONSENT_FLOW: Retrying tool '{original_tc['name']}' with consent JWT (preview: {jwt_preview})")
    
    original_args = dict(original_tc.get("args", {}))
    existing_headers = original_args.get("headers", {}) or {}
    logger.info(f"🔐 CONSENT_FLOW: Original headers before injection: {existing_headers}")
    original_args["headers"] = {**existing_headers, "Consent-JWT": consent_jwt}
    logger.info(f"🔐 CONSENT_FLOW: Headers after Consent-JWT injection: {list(original_args['headers'].keys())}")
    
    # Find the tool function from the graph's tool node
    configurable = config.get("configurable", {}) if config else {}
    tools_by_name = configurable.get("tools_by_name", {})
    tool_fn = tools_by_name.get(original_tc["name"])
    
    if not tool_fn:
        logger.error(f"Tool '{original_tc['name']}' not found in tools_by_name for consent retry")
        error_message = ToolMessage(
            content=f"Failed to retry with consent: tool '{original_tc['name']}' not found",
            tool_call_id=tool_call_id,
            status="error",
        )
        return {"messages": [error_message]}
    
    try:
        logger.info(f"🔐 CONSENT_FLOW: Invoking tool '{original_tc['name']}' with modified args (headers include Consent-JWT)")
        result = await tool_fn.ainvoke(original_args)
        logger.info(f"🔐 CONSENT_FLOW: Tool invocation completed, result type: {type(result)}, preview: {str(result)[:200]}")
        retry_message = ToolMessage(
            content=str(result),
            tool_call_id=tool_call_id,
            status="success",
        )
        logger.info(f"🔐 CONSENT_FLOW: Consent retry successful for tool '{original_tc['name']}', returning new ToolMessage")
        return {"messages": [retry_message]}
    except Exception as e:
        logger.error(f"🔐 CONSENT_FLOW: Consent retry failed for tool '{original_tc['name']}': {e}", exc_info=True)
        error_message = ToolMessage(
            content=f"Consent retry failed: {str(e)}",
            tool_call_id=tool_call_id,
            status="error",
        )
        return {"messages": [error_message]}

