from auth.auth import BaseAuth
from typing import Annotated

from auth.session import session_verifier, SessionData
from auth.auth import OBPConsentAuth
from fastapi import Depends

from agent import opey_graph, opey_graph_no_obp_tools, compile_opey_graph_with_tools
from agent.components.tools import endpoint_retrieval_tool, glossary_retrieval_tool

from agent.utils.obp import OBPRequestsModule
from service.checkpointer import get_global_checkpointer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import os
import logging

logger = logging.getLogger(__name__)

class OpeySession:
    """
    Class to manage Opey sessions.
    """
    def __init__(self, session_data: Annotated[SessionData, Depends(session_verifier)], checkpointer: Annotated[AsyncSqliteSaver, Depends(get_global_checkpointer)]):
        # Get consent_jwt from the session data
        self.consent_jwt = session_data.consent_jwt

        # Set up a new auth module to store the consent_jwt, then pass this to the OBP requests module
        # This is so that the OBP requests module can use the consent_jwt to authenticate requests
        # to the OBP API
        self.auth = OBPConsentAuth(consent_jwt=self.consent_jwt)
        self.obp_requests = OBPRequestsModule(auth=self.auth)

        # Need to create the OBP requests langchain tool here, as it relies on the consent_jwt header being set
        self.obp_requests_tool = self.obp_requests.langchain_tool

        # Set options for Opey to be used without any OBP tools
        if os.getenv("DISABLE_OBP_CALLING") == "true":
            logger.info("Disabling OBP tools: Calls to the OBP-API will not be available")

            tools = [endpoint_retrieval_tool, glossary_retrieval_tool]

        elif os.getenv("DISABLE_OBP_CALLING") == "false":
            logger.info("Enabling OBP tools: Calls to the OBP-API will be available")

            tools = [endpoint_retrieval_tool, glossary_retrieval_tool, self.obp_requests_tool]
            
        else:
            raise ValueError("DISABLE_OBP_CALLING must be set to 'true' or 'false'")
        
        self.graph = compile_opey_graph_with_tools(tools)

        self.graph.checkpointer = checkpointer
        