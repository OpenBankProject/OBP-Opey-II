"""
Reactive recovery for LLM context-window overflow.

The graph already has *proactive* safeguards:
- `sanitize_tool_responses` caps each ToolMessage to MAX_TOOL_CONTENT_CHARS.
- `preflight_safety_check` summarizes when state exceeds a threshold.

This module is the *reactive* counterpart: if the LLM call still fails with
a context-window error (because preflight under-counted, or a non-string
tool result bypassed the per-message cap, or system prompt + tool schemas
ate more headroom than the safety margin), we shrink the state in
progressively more aggressive steps and retry — instead of crashing the
stream with a 400.

The cascade (cheapest → most aggressive):
  1. Hard re-cap every ToolMessage to a tiny cap.
  2. Force summarization (collapse history into a summary).
  3. Drop the largest remaining ToolMessage (replace with a stub).
  4. Graceful degrade: return a synthetic AIMessage explaining the
     truncation, so the stream ends cleanly with a useful next-action.

Each step returns:
- `messages_for_call`: the list to invoke the LLM with on retry.
- `state_updates`: dicts that will be merged into the node's return so the
  shrinking persists (otherwise the next turn hits the same wall).
"""
import logging
from typing import Any, Dict, List, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger("uvicorn.error")


# Cap for hard re-cap step. Deliberately small — the goal is "make it fit",
# not "preserve detail". The agent can re-query for specifics if needed.
HARD_RECAP_CHARS = 1000


_OVERFLOW_PHRASES = (
    "prompt is too long",        # Anthropic
    "context_length_exceeded",   # OpenAI
    "maximum context length",    # OpenAI (alt phrasing)
    "context window",            # Generic / Bedrock
    "too many tokens",           # Generic fallback
)


def _is_context_overflow(exc: BaseException) -> bool:
    """True if `exc` (or anything it wraps) looks like a context-window error.

    Walks the cause/context chain so we catch wrapped errors raised from
    inside LangGraph / LangChain / Anthropic SDK layers.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        msg = str(current).lower()
        if any(phrase in msg for phrase in _OVERFLOW_PHRASES):
            return True
        # Anthropic SDK BadRequestError exposes the API body in .body or .response
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            body_text = str(body).lower()
            if any(phrase in body_text for phrase in _OVERFLOW_PHRASES):
                return True
        current = current.__cause__ or current.__context__
    return False


def _content_length(content: Any) -> int:
    """Approximate character length of a message content payload."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, dict):
                total += len(item.get("text", ""))
                if not item.get("text"):
                    total += len(str(item))
            else:
                total += len(str(item))
        return total
    return len(str(content))


def _shrink_tool_message(msg: ToolMessage, cap_chars: int) -> ToolMessage:
    """Return a copy of `msg` with its content hard-truncated to cap_chars."""
    content = msg.content
    if isinstance(content, str):
        if len(content) <= cap_chars:
            return msg
        new_content = content[:cap_chars] + "\n\n[TRUNCATED BY RECOVERY]"
    elif isinstance(content, list):
        combined = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
        if len(combined) <= cap_chars:
            return msg
        new_content = [{
            "type": "text",
            "text": combined[:cap_chars] + "\n\n[TRUNCATED BY RECOVERY]",
        }]
    else:
        coerced = str(content)
        if len(coerced) <= cap_chars:
            new_content = coerced
        else:
            new_content = coerced[:cap_chars] + "\n\n[TRUNCATED BY RECOVERY]"
    return msg.model_copy(update={"content": new_content})


# ---------------------------------------------------------------------------
# Step 1: hard re-cap every ToolMessage
# ---------------------------------------------------------------------------


def hard_recap_tool_messages(
    messages: List[BaseMessage],
    cap_chars: int = HARD_RECAP_CHARS,
) -> Tuple[List[BaseMessage], List[ToolMessage]]:
    """Re-cap every ToolMessage to `cap_chars`.

    Returns:
      (messages_for_call, replacements_to_persist)
      - messages_for_call: same list with capped ToolMessages substituted.
      - replacements_to_persist: only the changed ToolMessages, same IDs,
        suitable to return from a node so the add_messages reducer updates
        them in place.
    """
    new_messages: List[BaseMessage] = []
    replacements: List[ToolMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            shrunk = _shrink_tool_message(msg, cap_chars)
            if shrunk is not msg:
                replacements.append(shrunk)
            new_messages.append(shrunk)
        else:
            new_messages.append(msg)
    logger.warning(
        f"recovery step 1: hard-recapped {len(replacements)} ToolMessage(s) "
        f"to {cap_chars} chars"
    )
    return new_messages, replacements


# ---------------------------------------------------------------------------
# Step 2: force summarization
# ---------------------------------------------------------------------------


async def force_summarize(
    state_messages: List[BaseMessage],
    state: Dict[str, Any],
) -> Tuple[List[BaseMessage], Dict[str, Any]]:
    """Run the conversation summarizer and return a reduced message list.

    Delegates to `run_summary_chain` (the same one the proactive
    `preflight_safety_check` uses) so behaviour stays consistent.

    Returns:
      (messages_for_call, state_updates)
      - messages_for_call: [SystemMessage(summary)] + kept messages.
      - state_updates: the dict returned by run_summary_chain (contains
        RemoveMessage entries + conversation_summary + total_tokens reset).
    """
    # Import here to avoid a circular import (nodes.py imports nothing from
    # recovery, but recovery is consumed by graph_builder which already
    # imports nodes).
    from agent.components.nodes import run_summary_chain

    pseudo_state = {**state, "messages": state_messages}
    state_updates = await run_summary_chain(pseudo_state)

    removed_ids = {
        m.id for m in state_updates.get("messages", []) if isinstance(m, RemoveMessage)
    }
    kept = [m for m in state_messages if m.id not in removed_ids]

    summary_text = state_updates.get("conversation_summary", "")
    if summary_text:
        kept = [
            SystemMessage(content=f"Summary of earlier conversation: {summary_text}")
        ] + kept

    logger.warning(
        f"recovery step 2: summarized {len(removed_ids)} message(s); "
        f"retrying with {len(kept)} message(s)"
    )
    return kept, state_updates


# ---------------------------------------------------------------------------
# Step 3: drop the largest remaining ToolMessage
# ---------------------------------------------------------------------------


def drop_largest_tool_message(
    messages: List[BaseMessage],
) -> Tuple[List[BaseMessage], List[ToolMessage]]:
    """Replace the largest ToolMessage with a stub.

    Preserves the tool_use / tool_result pairing (so the assistant knows
    *which* call's result was dropped) but strips the body. Crucially does
    NOT remove the message — removing only the ToolMessage would orphan its
    parent AIMessage tool_call, breaking Anthropic's message format.

    Returns:
      (messages_for_call, replacements_to_persist)
    """
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    if not tool_msgs:
        logger.warning(
            "recovery step 3: no ToolMessages to drop — nothing to do"
        )
        return messages, []

    target = max(tool_msgs, key=lambda m: _content_length(m.content))
    stub_text = (
        "[tool response dropped by recovery to fit context window; "
        "please ask a more specific question if you need this data]"
    )
    stub = target.model_copy(update={"content": stub_text})

    new_messages = [stub if m is target else m for m in messages]
    logger.warning(
        f"recovery step 3: dropped largest ToolMessage "
        f"(tool_call_id={target.tool_call_id}, original ~{_content_length(target.content)} chars)"
    )
    return new_messages, [stub]


# ---------------------------------------------------------------------------
# Step 4: graceful degrade
# ---------------------------------------------------------------------------


def _content_to_text(content: Any) -> str:
    """Best-effort flatten of message content to a plain string for inspection."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", "") or str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _summarize_last_tool_result(messages: List[BaseMessage]) -> str | None:
    """Inspect the last ToolMessage and produce a one-line human summary.

    Goal: tell the user *what came back* from the bank, so a failed LLM call
    doesn't look like "Opey did nothing". Best-effort and safe — returns
    None if we can't extract anything useful.
    """
    last_tool: ToolMessage | None = None
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            last_tool = msg
            break
    if last_tool is None:
        return None

    text = _content_to_text(last_tool.content)
    if not text:
        return None

    # Heuristic: parse JSON, look for an obvious list of records.
    try:
        import json
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return f"the last tool call returned {len(text):,} characters of data"

    response = parsed.get("response", parsed) if isinstance(parsed, dict) else parsed
    if isinstance(response, dict):
        for key, value in response.items():
            if isinstance(value, list):
                return f"the OBP API returned {len(value)} `{key}` (≈ {len(text):,} chars)"
        return f"the OBP API returned an object with keys: {', '.join(list(response.keys())[:6])}"
    if isinstance(response, list):
        return f"the OBP API returned {len(response)} items (≈ {len(text):,} chars)"
    return f"the OBP API returned {len(text):,} characters of data"


def graceful_failure_message(messages: List[BaseMessage] | None = None) -> AIMessage:
    """Synthetic AIMessage used when every recovery step has failed.

    Returning this to state lets the stream end cleanly with a useful
    next-action for the user instead of bubbling a 400 to the portal.

    If `messages` is provided, inspects the most recent ToolMessage and
    reports what data was actually retrieved — so the user knows the bank
    call succeeded, only the summarization step failed.
    """
    logger.error(
        "recovery step 4: all recovery steps exhausted — emitting graceful "
        "degrade message to caller"
    )

    retrieved_line = ""
    if messages:
        summary = _summarize_last_tool_result(messages)
        if summary:
            retrieved_line = (
                f"\n\n**Good news — the bank call succeeded:** "
                f"{summary}.\n"
                f"It was too large for me to summarize in one go."
            )

    text = (
        "I couldn't fit the result of this turn into my context window."
        + retrieved_line
        + "\n\nPlease try a more specific question — for example, ask for "
        "a single record by id, narrow the time range, or filter by a "
        "specific bank or account."
    )
    return AIMessage(content=text)
