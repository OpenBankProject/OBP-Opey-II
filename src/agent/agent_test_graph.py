from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.checkpoint.memory import MemorySaver

from agent.components.states import OpeyGraphState
from agent.components.nodes import run_opey, human_review_node, run_summary_chain
from agent.components.edges import should_summarize, needs_human_review
from agent.components.tools import glossary_retrieval_tool, endpoint_retrieval_tool, obp_requests


memory = MemorySaver()

opey_workflow = StateGraph(OpeyGraphState)

# Define tools node
all_tools = ToolNode([glossary_retrieval_tool, endpoint_retrieval_tool, obp_requests])

# Add Nodes to graph
opey_workflow.add_node("opey", run_opey)
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

opey_test_graph = opey_workflow.compile(checkpointer=memory)