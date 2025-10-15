from langgraph.graph import END, StateGraph, START
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.tools import BaseTool
from langchain_core.prompts import SystemMessagePromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.language_models.chat_models import BaseChatModel

from agent.components.states import OpeyGraphState
from agent.components.chains import opey_system_prompt_template
from agent.components.nodes import human_review_node, run_summary_chain
from agent.components.edges import should_summarize, needs_human_review

from agent.utils.model_factory import get_model

from typing import List, Optional, Dict, Any, Literal
import os

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
        self._system_prompt: str = opey_system_prompt_template
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
        
        async def run_opey(state: OpeyGraphState):
            # Check if we have a conversation summary
            summary = state.get("conversation_summary", "")
            if summary:
                summary_system_message = f"Summary of earlier conversation: {summary}"
                messages = [SystemMessage(content=summary_system_message)] + state["messages"]
            else:
                messages = state["messages"]

            response = await opey_agent.ainvoke({"messages": messages})

            # Count the tokens in the messages
            total_tokens = state.get("total_tokens", 0)
            # Use the same LLM for token counting, but without tools binding
            # Use the same model for token counting, but without tools binding
            counting_llm = get_model(self._model_name, **self._model_kwargs)
            
            try:
                total_tokens += counting_llm.get_num_tokens_from_messages(messages)
            except NotImplementedError as e:
                print(f"Could not count tokens for model provider {os.getenv('MODEL_PROVIDER')}:\n{e}\n\nDefaulting to OpenAI GPT-4o counting...")
                from langchain_openai import ChatOpenAI
                total_tokens += ChatOpenAI(model='gpt-4o').get_num_tokens_from_messages(messages)

            return {"messages": response, "total_tokens": total_tokens}
        
        return run_opey
    

    def build(self) -> CompiledStateGraph:
        """Build and compile the agent graph"""
        opey_workflow = StateGraph(OpeyGraphState)
        
        # Create nodes
        opey_node = self._create_opey_node()
        opey_workflow.add_node("opey", opey_node)
        
        if self._tools:
            all_tools = ToolNode(self._tools)
            opey_workflow.add_node("tools", all_tools)
        
        if self._enable_human_review:
            opey_workflow.add_node("human_review", human_review_node)
        
        if self._enable_summarization:
            opey_workflow.add_node("summarize_conversation", run_summary_chain)
        
        # Add edges
        opey_workflow.add_edge(START, "opey")
        
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
        
        if self._tools:
            opey_workflow.add_edge("tools", "opey")
        
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