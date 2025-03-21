import os

from service import opey_instance
from langchain_core.runnables.graph import MermaidDrawMethod

def generate_mermaid_diagram(path: str):
    """
    Generate a mermaid diagram from the agent graph
    path (str): The path to save the diagram
    """
    try:
        if os.path.exists(path):
            os.remove(path)
        graph_png = opey_instance.get_graph().draw_mermaid_png(
            draw_method=MermaidDrawMethod.API,
            output_file_path=path,
        )
        return graph_png
    except Exception as e:
        print("Error generating mermaid diagram:", e)
        return None 