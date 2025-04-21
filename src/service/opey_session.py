from auth.auth import BaseAuth
from typing import Annotated

from auth.session import session_verifier, SessionData
from auth.auth import OBPConsentAuth
from fastapi import Depends

from agent import compile_opey_graph_with_tools, compile_opey_graph_with_tools_no_HIL
from agent.components.tools import endpoint_retrieval_tool, glossary_retrieval_tool

from agent.utils.obp import OBPRequestsModule
from service.checkpointer import get_global_checkpointer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.runnables.graph import MermaidDrawMethod


import os
import logging

logger = logging.getLogger('uvicorn.info')

class OpeySession:
    """
    Class to manage Opey sessions.
    """
    def __init__(self, session_data: Annotated[SessionData, Depends(session_verifier)], checkpointer: Annotated[BaseCheckpointSaver, Depends(get_global_checkpointer)]):
        # Get consent_jwt from the session data
        self.consent_jwt = session_data.consent_jwt
        self.auth = OBPConsentAuth(consent_jwt=self.consent_jwt)

        obp_api_mode = os.getenv("OBP_API_MODE")

        if obp_api_mode != "NONE":
            # Initialize the OBPRequestsModule with the auth object
            self.obp_requests = OBPRequestsModule(self.auth)

        # Base tools that all modes should have:
        base_tools = [endpoint_retrieval_tool, glossary_retrieval_tool]
        # Initialize the graph with the appropriate tools based on the OBP API mode
        match obp_api_mode:
            case "NONE":
                logger.info("OBP API mode set to NONE: Calls to the OBP-API will not be available")
                tools = base_tools
                self.graph = compile_opey_graph_with_tools_no_HIL(tools)

            case "SAFE":
                logger.info("OBP API mode set to SAFE: GET requests to the OBP-API will be available")
                tools = base_tools + [self.obp_requests.get_langchain_tool('safe')]
                # We don't need Human in the loop for SAFE mode, as only GET requests are made

                logger.info("Compiling graph with request tool: %s", tools[-1])
                self.graph = compile_opey_graph_with_tools_no_HIL(tools)

            case "DANGEROUS":
                logger.info("OBP API mode set to DANGEROUS: All requests to the OBP-API will be available subject to user approval.")
                tools = base_tools + [self.obp_requests.get_langchain_tool('dangerous')]
                self.graph = compile_opey_graph_with_tools(tools)

            case "TEST":
                logger.info("OBP API mode set to TEST: All requests to the OBP-API will be available AND WILL BE APPROVED BY DEFAULT. DO NOT USE IN PRODUCTION.")
                tools = base_tools + [self.obp_requests.get_langchain_tool('test')]
                self.graph = compile_opey_graph_with_tools_no_HIL(tools)

            case _:
                logger.error(f"OBP API mode set to {obp_api_mode}: Unknown OBP API mode. Defaulting to NONE.")
                tools = base_tools
                self.graph = compile_opey_graph_with_tools_no_HIL(tools)


        self.graph.checkpointer = checkpointer
    
    
    def get_threads_for_user(self):
        """
        Get the threads for the user
        Returns:
            List of threads for the user
        """
        raise NotImplementedError("This method is not implemented yet")
        

    def generate_mermaid_diagram(self, path: str):
        """
        Generate a mermaid diagram from the agent graph
        path (str): The path to save the diagram
        """
        try:
            if os.path.exists(path):
                os.remove(path)
            graph_png = self.graph.get_graph().draw_mermaid_png(
                draw_method=MermaidDrawMethod.API,
                output_file_path=path,
            )
            return graph_png
        except Exception as e:
            print("Error generating mermaid diagram:", e)
            return None 