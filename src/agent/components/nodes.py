import json
import uuid
import os
import logging

from typing import List, Dict

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

    # Build an index: tool_call_id -> parent AIMessage (from full conversation)
    tool_call_id_to_ai_msg: Dict[str, AIMessage] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_call_id_to_ai_msg[tc["id"]] = msg

    # Collect IDs of messages we must keep
    trimmed_ids = {msg.id for msg in trimmed_messages}

    # For every ToolMessage in the trimmed set, ensure its parent AIMessage is included
    required_ai_msg_ids = set()
    for msg in trimmed_messages:
        if isinstance(msg, ToolMessage):
            parent_ai = tool_call_id_to_ai_msg.get(msg.tool_call_id)
            if parent_ai:
                required_ai_msg_ids.add(parent_ai.id)
                trimmed_ids.add(parent_ai.id)
            else:
                logger.warning(f"Could not find parent AIMessage for ToolMessage {msg.id} (tool_call_id={msg.tool_call_id})")

    # For every required AIMessage, ensure ALL its sibling ToolMessages are included
    # This fixes the batch tool_use bug: if an AIMessage has N tool_uses, all N ToolMessages must be present
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.id in required_ai_msg_ids and msg.tool_calls:
            for tc in msg.tool_calls:
                # Find the ToolMessage for this tool_call_id
                for candidate in messages:
                    if isinstance(candidate, ToolMessage) and candidate.tool_call_id == tc["id"]:
                        trimmed_ids.add(candidate.id)
                        break

    # Also handle AIMessages already in trimmed set that have tool_calls — ensure their ToolMessages are included too
    for msg in trimmed_messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                for candidate in messages:
                    if isinstance(candidate, ToolMessage) and candidate.tool_call_id == tc["id"]:
                        trimmed_ids.add(candidate.id)
                        break

    # Rebuild trimmed_messages from original messages to preserve correct ordering
    trimmed_messages = [msg for msg in messages if msg.id in trimmed_ids]

    logger.debug(f"Trimmed messages after repair ({len(trimmed_messages)} messages):")
    for msg in trimmed_messages:
        logger.debug(f"  {type(msg).__name__} id={msg.id}")

    delete_messages = [RemoveMessage(id=message.id) for message in messages if message.id not in trimmed_ids]

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


async def _retry_tool_with_consent(
    tool_call_id: str,
    error_msg_id: str,
    original_tc: Dict,
    consent_jwt: str,
    tools_by_name: Dict,
) -> ToolMessage:
    """Retry a single tool call with an injected Consent-JWT. Returns a replacement ToolMessage."""
    tool_name = original_tc["name"]
    tool_fn = tools_by_name.get(tool_name)
    if not tool_fn:
        logger.error(f"🔐 CONSENT_FLOW: Tool '{tool_name}' not found in tools_by_name for consent retry")
        return ToolMessage(
            content=f"Failed to retry with consent: tool '{tool_name}' not found",
            tool_call_id=tool_call_id,
            id=error_msg_id,
            status="error",
        )

    original_args = dict(original_tc.get("args", {}))
    existing_headers = original_args.get("headers", {}) or {}
    original_args["headers"] = {**existing_headers, "Consent-JWT": consent_jwt}

    try:
        logger.info(f"🔐 CONSENT_FLOW: Retrying '{tool_name}' (tool_call_id={tool_call_id}) with Consent-JWT")
        result = await tool_fn.ainvoke(original_args)
        return ToolMessage(
            content=result,
            tool_call_id=tool_call_id,
            id=error_msg_id,
            status="success",
        )
    except Exception as e:
        logger.error(f"🔐 CONSENT_FLOW: Consent retry failed for '{tool_name}': {e}", exc_info=True)
        return ToolMessage(
            content=f"Consent retry failed: {str(e)}",
            tool_call_id=tool_call_id,
            id=error_msg_id,
            status="error",
        )


async def consent_check_node(state: OpeyGraphState, config: RunnableConfig):
    """
    Check tool responses for consent_required errors from MCP servers.

    Handles batch tool calls correctly: when multiple tool calls fail with
    consent_required, they are grouped by operation_id. Each distinct operation
    triggers one interrupt (and requires its own Consent-JWT, since JWTs are
    scoped per operation). Tool calls sharing the same operation_id are retried
    together using that operation's JWT.

    Uses the add_messages reducer's update-by-ID feature: returning a ToolMessage
    with the same ID as the original error message replaces it in-place.

    Flow:
        1. Scan all ToolMessages for consent_required errors
        2. Group by operation_id
        3. For each distinct operation: interrupt() → get JWT → retry all tools for that op
        4. Return all replacement ToolMessages at once
    """
    messages = state["messages"]
    if not messages:
        return {}

    # Only scan the most recent batch of ToolMessages (since the last AIMessage with
    # tool_calls). This prevents old unresolved consent errors from previous turns
    # re-triggering the interrupt when the user sends a new message.
    last_ai_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage) and getattr(msg, 'tool_calls', None):
            last_ai_idx = i
            break

    if last_ai_idx < 0:
        logger.debug("🔐 CONSENT_FLOW: No AIMessage with tool_calls found, passing through")
        return {}

    recent_messages = messages[last_ai_idx + 1:]

    # Collect consent_required ToolMessages from the current batch only
    consent_errors = []
    for msg in recent_messages:
        if isinstance(msg, ToolMessage):
            consent_info = _parse_consent_error(msg)
            if consent_info:
                original_tc = _find_tool_call_for_message(messages, msg.tool_call_id)
                if original_tc:
                    logger.info(
                        f"🔐 CONSENT_FLOW: Detected consent_required error "
                        f"(tool_call_id={msg.tool_call_id}, operation={consent_info.get('operation_id')})"
                    )
                    consent_errors.append({
                        "error_msg": msg,
                        "consent_info": consent_info,
                        "original_tc": original_tc,
                    })
                else:
                    logger.error(f"🔐 CONSENT_FLOW: Could not find original tool call for tool_call_id={msg.tool_call_id}")

    if not consent_errors:
        logger.debug("🔐 CONSENT_FLOW: No consent errors found, passing through")
        return {}

    # Group by operation_id — each distinct operation needs its own Consent-JWT
    # (JWTs are scoped to specific operations/roles in OBP)
    groups: Dict[str, list] = {}
    for ce in consent_errors:
        op_id = ce["consent_info"].get("operation_id") or "__unknown__"
        groups.setdefault(op_id, []).append(ce)

    logger.info(
        f"🔐 CONSENT_FLOW: {len(consent_errors)} consent error(s) across "
        f"{len(groups)} distinct operation(s): {list(groups.keys())}"
    )

    configurable = config.get("configurable", {}) if config else {}
    tools_by_name = configurable.get("tools_by_name", {})

    all_replacements = []

    for op_id, group in groups.items():
        first = group[0]
        required_roles = first["consent_info"].get("required_roles", [])
        tool_call_ids = [ce["error_msg"].tool_call_id for ce in group]

        # Build the interrupt payload — one per distinct operation
        consent_payload = {
            "consent_type": "consent_required",
            # Primary fields (used by stream_manager to emit ConsentRequestEvent)
            "tool_call_id": first["error_msg"].tool_call_id,
            "tool_name": first["original_tc"]["name"],
            "operation_id": op_id if op_id != "__unknown__" else None,
            "required_roles": required_roles,
            "bank_id": first["consent_info"].get("bank_id"),
            # Batch context so the frontend can show "N tool calls need this consent"
            "tool_call_count": len(group),
            "tool_call_ids": tool_call_ids,
        }

        logger.info(
            f"🔐 CONSENT_FLOW: Interrupting for operation '{op_id}' "
            f"({len(group)} tool call(s): {tool_call_ids})"
        )
        user_response = interrupt(consent_payload)
        logger.info(
            f"🔐 CONSENT_FLOW: Resumed for operation '{op_id}', "
            f"response keys: {list(user_response.keys()) if isinstance(user_response, dict) else type(user_response)}"
        )

        consent_jwt = user_response.get("consent_jwt")

        if not consent_jwt:
            logger.warning(f"🔐 CONSENT_FLOW: Consent denied for operation '{op_id}' — denying {len(group)} tool call(s)")
            for ce in group:
                all_replacements.append(ToolMessage(
                    content="End user denied consent for this tool.",
                    tool_call_id=ce["error_msg"].tool_call_id,
                    id=ce["error_msg"].id,
                    status="error",
                ))
        else:
            jwt_preview = consent_jwt[:50] + "..." if len(consent_jwt) > 50 else consent_jwt
            logger.info(
                f"🔐 CONSENT_FLOW: Consent approved for operation '{op_id}' (JWT preview: {jwt_preview}) "
                f"— retrying {len(group)} tool call(s)"
            )
            for ce in group:
                replacement = await _retry_tool_with_consent(
                    tool_call_id=ce["error_msg"].tool_call_id,
                    error_msg_id=ce["error_msg"].id,
                    original_tc=ce["original_tc"],
                    consent_jwt=consent_jwt,
                    tools_by_name=tools_by_name,
                )
                all_replacements.append(replacement)

    return {"messages": all_replacements}

