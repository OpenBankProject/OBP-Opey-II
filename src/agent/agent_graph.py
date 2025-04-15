from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import BaseTool

from agent.components.states import OpeyGraphState
from agent.components.nodes import run_opey, human_review_node, run_summary_chain
from agent.components.edges import should_summarize, needs_human_review
from agent.components.tools import obp_requests, glossary_retrieval_tool, endpoint_retrieval_tool

from typing import List

memory = MemorySaver()

opey_workflow = StateGraph(OpeyGraphState)

# Define tools node
all_tools = ToolNode([glossary_retrieval_tool, endpoint_retrieval_tool, obp_requests])

# Add Nodes to graph
opey_workflow.add_node("opey", run_opey)
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

def compile_opey_graph_with_tools(tools: List[BaseTool]):
    opey_workflow = StateGraph(OpeyGraphState)
    all_tools = ToolNode(tools)

    opey_workflow.add_node("opey", run_opey)
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


opey_graph = opey_workflow.compile(checkpointer=memory, interrupt_before=["human_review"])