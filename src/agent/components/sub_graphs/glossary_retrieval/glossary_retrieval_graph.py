from langgraph.graph import StateGraph, START, END
from agent.components.sub_graphs.glossary_retrieval.components.states import SelfRAGGraphState, InputState, OutputState
from agent.components.sub_graphs.glossary_retrieval.components.nodes import retrieve_glossary, grade_documents_glossary, return_documents

# Glossary retrieval graph definition
# NOTE: Some components are shared with the endpoint retrieval graph

glossary_retrieval_workflow = StateGraph(SelfRAGGraphState, input=InputState, output=OutputState)

glossary_retrieval_workflow.add_node("retrieve_items", retrieve_glossary)
glossary_retrieval_workflow.add_node("grade_documents", grade_documents_glossary)
glossary_retrieval_workflow.add_node("return_documents", return_documents)

glossary_retrieval_workflow.add_edge(START, "retrieve_items")
glossary_retrieval_workflow.add_edge("retrieve_items", "grade_documents")
glossary_retrieval_workflow.add_edge("grade_documents", "return_documents")
glossary_retrieval_workflow.add_edge("return_documents", END)

glossary_retrieval_graph = glossary_retrieval_workflow.compile()