from langgraph.graph import END, StateGraph, START
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.tools import BaseTool
from langchain_core.prompts import SystemMessagePromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import Runnable
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from agent.components.states import OpeyGraphState
from agent.components.chains import opey_system_prompt_template
from agent.components.nodes import human_review_node, run_summary_chain, sanitize_tool_responses, consent_check_node, preflight_safety_check
from agent.components.recovery import (
    _is_context_overflow,
    drop_largest_tool_message,
    force_summarize,
    graceful_failure_message,
    hard_recap_tool_messages,
)
from agent.components.edges import should_summarize, needs_human_review
from agent.utils.model_factory import get_model
from agent.utils.decorators import cancellable
from agent.utils.token_counter import count_tokens_from_messages

from typing import List, Optional, Dict, Any, Literal, Tuple
import logging
import os

from langchain_core.messages import AIMessage, BaseMessage

logger = logging.getLogger("uvicorn.error")


async def _invoke_with_recovery(
    opey_agent: Runnable,
    messages: List[BaseMessage],
    state: "OpeyGraphState",
    config: RunnableConfig,
) -> Tuple[AIMessage, Dict[str, Any], List[BaseMessage]]:
    """Invoke the LLM and recover from context-window overflow.

    Cascade (each step retries the LLM with a smaller payload):
      1. Hard re-cap every ToolMessage to ~1000 chars.
      2. Force-summarize the conversation.
      3. Drop the largest ToolMessage (replace body with a stub).
      4. Graceful degrade: synthesize an AIMessage telling the user we
         dropped context and to ask more specifically.

    Returns:
      (response, state_updates, final_messages)
      - response: AIMessage to emit (real or synthetic).
      - state_updates: dict to merge into the node's return so the shrinking
        persists. May contain `messages` (replacements/removes),
        `conversation_summary`, `total_tokens`.
      - final_messages: the actual list invoked against the LLM, for token
        accounting.
    """
    try:
        response = await opey_agent.ainvoke({"messages": messages}, config)
        return response, {}, messages
    except Exception as exc:
        if not _is_context_overflow(exc):
            # Log the full exception chain so we can tell whether overflow is
            # being wrapped in a way the predicate doesn't recognise.
            chain = []
            cur: BaseException | None = exc
            while cur is not None and len(chain) < 6:
                chain.append(f"{type(cur).__name__}: {str(cur)[:200]}")
                cur = cur.__cause__ or cur.__context__
            logger.error(
                f"opey: ainvoke raised non-overflow exception: {' <- '.join(chain)}"
            )
            raise
        logger.warning(f"opey: context overflow on first call: {exc!r}; entering recovery cascade")

    state_updates: Dict[str, Any] = {}
    accumulated_replacements: List[BaseMessage] = []

    # Step 1: hard re-cap all ToolMessages
    messages, reps = hard_recap_tool_messages(messages)
    accumulated_replacements.extend(reps)
    try:
        response = await opey_agent.ainvoke({"messages": messages}, config)
        state_updates["messages"] = accumulated_replacements
        return response, state_updates, messages
    except Exception as exc:
        if not _is_context_overflow(exc):
            raise
        logger.warning(f"opey: step 1 (hard re-cap) did not fit: {exc!r}; trying step 2")

    # Step 2: force-summarize
    messages, summary_updates = await force_summarize(messages, state)
    # Merge: RemoveMessages from summarization + tool-message replacements
    # from step 1 both go into `messages`. Order: replacements first so
    # add_messages updates content, then RemoveMessages drop what's left.
    summary_msg_updates = list(summary_updates.get("messages", []))
    state_updates = {
        **summary_updates,
        "messages": accumulated_replacements + summary_msg_updates,
    }
    try:
        response = await opey_agent.ainvoke({"messages": messages}, config)
        return response, state_updates, messages
    except Exception as exc:
        if not _is_context_overflow(exc):
            raise
        logger.warning(f"opey: step 2 (summarize) did not fit: {exc!r}; trying step 3")

    # Step 3: drop the largest remaining ToolMessage
    messages, drop_reps = drop_largest_tool_message(messages)
    state_updates["messages"] = accumulated_replacements + summary_msg_updates + drop_reps
    try:
        response = await opey_agent.ainvoke({"messages": messages}, config)
        return response, state_updates, messages
    except Exception as exc:
        if not _is_context_overflow(exc):
            raise
        logger.error(f"opey: step 3 (drop largest) did not fit: {exc!r}; graceful degrade")

    # Step 4: graceful degrade — no LLM call, return synthetic message
    # Pass current state messages so the message can report what data
    # was actually retrieved (the bank call succeeded; only summarization failed).
    response = graceful_failure_message(messages=state.get("messages", []))
    return response, state_updates, messages

class OpeyAgentGraphBuilder:
    """
    Builder pattern for creating flexible Opey agent configurations.
    
    Architecture Notes:
    -------------------
    When human_review is enabled, the graph follows a clean separation of concerns:
    
    1. **Edge Function (needs_human_review)**: Simple routing logic
       - Checks: "Are there tool calls?"
       - Routes to: human_review_node OR END
       - Does NOT duplicate approval logic
    
    2. **ToolRegistry**: Declarative approval rules
       - Defines which tools/patterns require approval
       - Provides metadata about risk levels, affected resources
       - Supports custom approval logic per tool
    
    3. **ApprovalManager**: Multi-level approval state
       - Checks existing approvals (session/user/workspace)
       - Persists approval decisions
       - Handles TTL and expiration
    
    4. **human_review_node**: Intelligent approval orchestration
       - Uses ToolRegistry to check if approval needed
       - Uses ApprovalManager to check for existing approvals
       - Only interrupts when truly needed
       - Handles approval decisions and persistence
    
    This design eliminates duplication and makes approval rules easy to modify
    without touching the graph structure.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset builder to default state"""
        self._tools: List[BaseTool] = []
        self._system_prompt: str = os.getenv("OPEY_SYSTEM_PROMPT", opey_system_prompt_template)
        self._model_name: str = "medium"
        self._temperature: float = 0.7
        self._checkpointer: Optional[BaseCheckpointSaver] = None
        self._enable_human_review: bool = False
        self._enable_summarization: bool = True
        self._prompt_additions: List[str] = []
        self._model_kwargs: Dict[str, Any] = {}
        return self
    
    def with_tools(self, tools: List[BaseTool]):
        """Specify tools to include in the agent"""
        self._tools = tools
        return self
    
    def add_tool(self, tool: BaseTool):
        """Add a single tool to the agent"""
        self._tools.append(tool)
        return self
    
    def with_system_prompt(self, prompt: str):
        """Set a custom system prompt."""
        self._system_prompt = prompt
        return self
    
    def add_to_system_prompt(self, addition: str):
        """
        Appends additional text to the end of the system prompt. 
        WARNING: Do not expose this to end users as it may lead to prompt injection attacks.
        Once we sanitize the input, we can consider exposing this more widely.
        TODO: https://meta-llama.github.io/PurpleLlama/LlamaFirewall/ add sanitization
        """
        self._prompt_additions.append(addition)
        return self
    
    def with_model(self, model_name: str = "medium", temperature: float = 0.7, **kwargs):
        """Configure the model by name or size category"""
        self._model_name = model_name
        self._temperature = temperature
        self._model_kwargs = kwargs
        return self
    
    
    def with_checkpointer(self, checkpointer: BaseCheckpointSaver):
        """Set a custom checkpointer for the graph"""
        self._checkpointer = checkpointer
        return self
    
    def enable_human_review(self, enable: bool = True):
        """Enable or disable human-in-the-loop review step"""
        self._enable_human_review = enable
        return self
    
    def _build_system_prompt(self) -> str:
        """Construct the final system prompt with any additions"""
        if not self._prompt_additions:
            return self._system_prompt

        prompt_parts = [self._system_prompt]
        prompt_parts.extend(self._prompt_additions)
        return "\n\n".join(prompt_parts)
    
    def _get_llm(self) -> Runnable:
        """Get the configured LLM"""
        # DIAGNOSTIC (temporary): log the size of every bound tool schema. The sum is the
        # fixed per-request overhead sent to the LLM on every call. Remove once resolved.
        try:
            from langchain_core.utils.function_calling import convert_to_openai_tool
            import json as _json
            _total = 0
            for _t in self._tools:
                _sz = len(_json.dumps(convert_to_openai_tool(_t)))
                _total += _sz
                logger.warning(f"[TOOL DIAG] {getattr(_t, 'name', _t)}: {_sz} chars")
            logger.warning(f"[TOOL DIAG] {len(self._tools)} tools, total schema {_total} chars (~{_total // 4} tokens)")
        except Exception as _diag_err:
            logger.warning(f"[TOOL DIAG] failed: {_diag_err}")

        return get_model(
            self._model_name,
            temperature=self._temperature,
            **self._model_kwargs
        ).bind_tools(self._tools)
    

    def _create_opey_node(self):
        """Create the Opey agent node"""
        opey_llm = self._get_llm()
        final_prompt = self._build_system_prompt()
        
        prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(final_prompt),
            MessagesPlaceholder("messages")
        ])
        
        opey_agent = prompt | opey_llm
        
        @cancellable(preserve_state_keys=["total_tokens"])
        async def run_opey(state: OpeyGraphState, config: RunnableConfig):
            # Ephemeral per-turn system context, prepended only for this LLM call (never
            # persisted to message history, so it always reflects the latest values).
            prepend: list[SystemMessage] = []

            summary = state.get("conversation_summary", "")
            if summary:
                prepend.append(SystemMessage(content=f"Summary of earlier conversation: {summary}"))

            current_bank_id = (config.get("configurable", {}) or {}).get("current_bank_id")
            if current_bank_id:
                prepend.append(SystemMessage(content=(
                    f"The user currently has OBP bank '{current_bank_id}' selected in the UI. "
                    f"When a request does not name a bank, use this bank_id."
                )))

            messages = prepend + state["messages"]

            # DIAGNOSTIC (temporary): locate context bloat. Logs message count, total
            # content size, and the 8 biggest messages. Remove once context issue is fixed.
            try:
                _sizes = sorted(
                    ((type(m).__name__, len(str(getattr(m, "content", "") or ""))) for m in messages),
                    key=lambda x: x[1], reverse=True,
                )
                logger.warning(
                    f"[CTX DIAG] {len(messages)} messages, "
                    f"~{sum(s for _, s in _sizes)} content chars (~{sum(s for _, s in _sizes) // 4} tokens); "
                    f"biggest 8: {_sizes[:8]}"
                )
            except Exception as _diag_err:
                logger.warning(f"[CTX DIAG] failed: {_diag_err}")

            # Anthropic rejects a request whose messages are all system content
            # ("at least one message is required"). If summarisation/trimming left
            # nothing to respond to, add a minimal user turn so the call is valid.
            if not any(not isinstance(m, SystemMessage) for m in messages):
                logger.warning("run_opey: only system messages present — appending a continuation HumanMessage")
                messages = messages + [HumanMessage(content="Please continue, based on the summary above.")]

            response, extra_updates, messages = await _invoke_with_recovery(
                opey_agent, messages, state, config
            )

            # Count the tokens in the messages
            total_tokens = state.get("total_tokens", 0)
            token_count = count_tokens_from_messages(messages, self._model_name, self._model_kwargs)
            total_tokens += token_count

            # Merge any state updates produced by the recovery cascade
            # (capped ToolMessage replacements, RemoveMessages from
            # summarization, updated conversation_summary, …) with the
            # assistant response. The add_messages reducer keys on .id, so
            # replacements update in place and removes drop in place.
            result: dict = {**extra_updates, "total_tokens": total_tokens}
            existing_msgs = extra_updates.get("messages", [])
            result["messages"] = list(existing_msgs) + [response] if existing_msgs else response
            return result

        return run_opey
    

    def build(self) -> CompiledStateGraph:
        """Build and compile the agent graph"""
        opey_workflow = StateGraph(OpeyGraphState)
        
        # Create nodes
        opey_node = self._create_opey_node()
        opey_workflow.add_node("opey", opey_node)
        opey_workflow.add_node("preflight_safety_check", preflight_safety_check)

        if self._tools:
            all_tools = ToolNode(self._tools)
            opey_workflow.add_node("tools", all_tools)
            opey_workflow.add_node("sanitize_tool_responses", sanitize_tool_responses)
            opey_workflow.add_node("consent_check", consent_check_node)
            opey_workflow.add_edge("tools", "sanitize_tool_responses")
            opey_workflow.add_edge("sanitize_tool_responses", "consent_check")
            opey_workflow.add_edge("consent_check", "preflight_safety_check")
        
        if self._enable_human_review:
            opey_workflow.add_node("human_review", human_review_node)
        
        if self._enable_summarization:
            opey_workflow.add_node("summarize_conversation", run_summary_chain)
        
        # Add edges
        opey_workflow.add_edge(START, "preflight_safety_check")
        opey_workflow.add_edge("preflight_safety_check", "opey")
        
        if self._enable_human_review:
            # Human review workflow
            # Route to human_review node when tool calls are present
            # The human_review_node will intelligently decide whether to interrupt
            opey_workflow.add_conditional_edges(
                "opey",
                needs_human_review,
                {
                    "human_review": "human_review",
                    END: END
                }
            )
            # After human_review, always proceed to tools (approval logic is in human_review_node)
            opey_workflow.add_edge("human_review", "tools" if self._tools else "opey")
        elif self._tools:
            # Direct tool routing
            opey_workflow.add_conditional_edges(
                "opey",
                tools_condition,
                {
                    "tools": "tools",
                    END: END
                }
            )
        
        # Note: tools → opey edge is already added via sanitize_tool_responses above (line 183)
        
        if self._enable_summarization:
            opey_workflow.add_conditional_edges(
                "opey",
                should_summarize,
                {
                    "summarize_conversation": "summarize_conversation",
                    END: END
                }
            )
            opey_workflow.add_edge("summarize_conversation", END)
        
        
        # Compile with appropriate settings
        compile_kwargs = {}
        if self._checkpointer:
            compile_kwargs["checkpointer"] = self._checkpointer
        else:
            compile_kwargs["checkpointer"] = MemorySaver()
        
        # Note: We no longer use interrupt_before because human_review_node
        # uses dynamic interrupt() internally. This allows the node to:
        # 1. Check pre-existing approvals first
        # 2. Only interrupt when actually needed
        # 3. Support batch approvals
        
        return opey_workflow.compile(**compile_kwargs)
    

# Convenience functions for common configurations
def create_basic_opey_graph(tools: List[BaseTool]) -> CompiledStateGraph:
    """Create a basic Opey graph with tools, no human review"""
    return (OpeyAgentGraphBuilder()
            .with_tools(tools)
            .enable_human_review(False)
            .build())


def create_supervised_opey_graph(tools: List[BaseTool]) -> CompiledStateGraph:
    """Create Opey graph with human review for dangerous operations"""
    return (OpeyAgentGraphBuilder()
            .with_tools(tools)
            .enable_human_review(True)
            .build())


def create_custom_opey_graph(
    tools: List[BaseTool],
    system_prompt_additions: Optional[List[str]] = None,
    model_size: str = "medium",
    temperature: float = 0.7,
    enable_human_review: bool = False,
    checkpointer: Optional[BaseCheckpointSaver] = None
) -> CompiledStateGraph:
    """Create a customized Opey graph"""
    builder = (OpeyAgentGraphBuilder()
               .with_tools(tools)
               .with_model(model_size, temperature)
               .enable_human_review(enable_human_review))
    
    if system_prompt_additions:
        for addition in system_prompt_additions:
            builder.add_to_system_prompt(addition)
    
    if checkpointer:
        builder.with_checkpointer(checkpointer)
    
    return builder.build()