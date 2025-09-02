from agent.components.sub_graphs.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.sub_graphs.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph

# Define endpoint retrieval tool nodes

endpoint_retrieval_tool = endpoint_retrieval_graph.as_tool(name="retrieve_endpoints")
glossary_retrieval_tool = glossary_retrieval_graph.as_tool(name="retrieve_glossary")