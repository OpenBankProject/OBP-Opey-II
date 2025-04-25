from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import BaseTool

from langchain_core.prompts import SystemMessagePromptTemplate, PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from agent.components.states import OpeyGraphState
from agent.components.chains import opey_system_prompt_template
from agent.components.nodes import human_review_node, run_summary_chain
from agent.components.edges import should_summarize, needs_human_review

from agent.utils.model_factory import get_llm

from typing import List

memory = MemorySaver()

def _create_opey_agent_node_with_tools(tools: List[BaseTool]):
    """
    Allows us to dynamically create the Opey agent node with the tools we want to use.
    """

    # bind_tools tells the LLM the tools it can use
    # this is different from having the ToolNode in the graph, as this only allows routing and executing the tools.
    # But opey needs to know about the tools to be able to use them in the prompt.
    opey_llm = get_llm("medium", temperature=0.7).bind_tools(tools)

    # NOTE: the system prompt template is defined in the chains.py file
    # but we could change this to pull a template from a remote repo in the future
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessagePromptTemplate.from_template(opey_system_prompt_template),
            MessagesPlaceholder("messages")
        ]
    )

    opey_agent = prompt | opey_llm

    # return a node (function) that runs opey
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

    return run_opey


def compile_opey_graph_with_tools(tools: List[BaseTool]):
    """
    Compiles and configures the Opey workflow graph with provided tools.
    This function creates a state graph that defines the flow of operations in the Opey system,
    including tool execution, human review processes, and conversation summarization.
    Parameters
    ----------
    tools : List[BaseTool]
        A list of tool objects that will be available for the agent to use during execution.
        These tools are wrapped in a ToolNode for the workflow.
    Returns
    -------
    CompiledGraph
        A compiled workflow graph that can be executed. The graph includes nodes for the main Opey agent,
        human review, tool execution, and conversation summarization. It's configured with
        checkpointing via the memory object and will interrupt execution before human review steps.
    Notes
    -----
    The graph defines the following workflow:
    1. Starts with the Opey agent
    2. Can transition to tools or human review based on conditional logic
    3. After human review, always proceeds to tools
    4. Tools execution returns to the Opey agent
    5. Can optionally summarize the conversation before ending
    """
    opey_node = _create_opey_agent_node_with_tools(tools)

    opey_workflow = StateGraph(OpeyGraphState)
    all_tools = ToolNode(tools)

    opey_workflow.add_node("opey", opey_node)
    opey_workflow.add_node("human_review", human_review_node)
    opey_workflow.add_node("tools", all_tools)
    opey_workflow.add_node("summarize_conversation", run_summary_chain)

    opey_workflow.add_conditional_edges(
        "opey",
        needs_human_review,
        {
            "tools": "tools",
            "human_review": "human_review",
            END: END
        }
    )

    opey_workflow.add_conditional_edges(
        "opey",
        should_summarize,
        {
            "summarize_conversation": "summarize_conversation",
            END: END
        }
    )

    opey_workflow.add_edge("human_review", "tools")
    opey_workflow.add_edge(START, "opey")
    opey_workflow.add_edge("tools", "opey")
    opey_workflow.add_edge("summarize_conversation", END)

    return opey_workflow.compile(checkpointer=memory, interrupt_before=["human_review"])


def compile_opey_graph_with_tools_no_HIL(tools: List[BaseTool]):
    """
    Compiles and configures the Opey workflow graph with provided tools.
    Removes the human review step from the workflow.
    """
    opey_workflow = StateGraph(OpeyGraphState)

    # Define tools node
    all_tools = ToolNode(tools)

    opey_node = _create_opey_agent_node_with_tools(tools)
    # Add Nodes to graph
    opey_workflow.add_node("opey", opey_node)
    opey_workflow.add_node("tools", all_tools)
    opey_workflow.add_node("summarize_conversation", run_summary_chain)


    # Route to RAG tools or not
    opey_workflow.add_conditional_edges(
        "opey",
        tools_condition,
        {
            "tools": "tools",
            END: END
        }
    )

    opey_workflow.add_conditional_edges(
        "opey",
        should_summarize,
        {
            "summarize_conversation": "summarize_conversation",
            END: END
        }
    )

    opey_workflow.add_edge(START, "opey")
    opey_workflow.add_edge("tools", "opey")
    opey_workflow.add_edge("summarize_conversation", END)

    return opey_workflow.compile(checkpointer=memory)
