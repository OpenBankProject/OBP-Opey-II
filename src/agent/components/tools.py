"""
DEPRECATED: This file is superseded by the tools/ directory.

The retrieval tools (endpoint_retrieval_tool, glossary_retrieval_tool) have been
integrated into an MCP server and are no longer defined here.

New code should:
- Import from agent.components.tools (the directory, not this file)
- Use MCPToolLoader to load tools from MCP servers

This file is kept for backwards compatibility with existing test code.
"""
import warnings
warnings.warn(
    "agent.components.tools (file) is deprecated. Tools now come from MCP servers.",
    DeprecationWarning,
    stacklevel=2
)

from agent.components.retrieval.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from agent.components.retrieval.glossary_retrieval.glossary_retrieval_graph import glossary_retrieval_graph

# Define endpoint retrieval tool nodes

endpoint_retrieval_tool = endpoint_retrieval_graph.as_tool(name="retrieve_endpoints")
glossary_retrieval_tool = glossary_retrieval_graph.as_tool(name="retrieve_glossary")