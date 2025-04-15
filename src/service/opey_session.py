from auth.auth import BaseAuth
from typing import Annotated

from auth.session import session_verifier, SessionData
from fastapi import Depends

from agent import opey_graph, opey_graph_no_obp_tools
from service.checkpointer import get_global_checkpointer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import os
import logging

logger = logging.getLogger(__name__)

class OpeyContext:
    """
    Class to manage Opey sessions.
    """
    def __init__(self, session_data: Annotated[SessionData, Depends(session_verifier)], checkpointer: Annotated[AsyncSqliteSaver, Depends(get_global_checkpointer)]):
        self.consent_jwt = session_data.consent_jwt

        if os.getenv("DISABLE_OBP_CALLING") == "true":
            logger.info("Disabling OBP tools: Calls to the OBP-API will not be available")
            self.graph = opey_graph_no_obp_tools
        else:
            logger.info("Enabling OBP tools: Calls to the OBP-API will be available")
            self.graph = opey_graph

        self.graph.checkpointer = checkpointer
        