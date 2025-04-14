from auth.auth import BaseAuth
from typing import Annotated

from auth.session import session_verifier, SessionData
from fastapi import Depends

from agent import opey_graph, opey_graph_no_obp_tools
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import os
import logging

logger = logging.getLogger(__name__)

async def setup_checkpointing():
    """
    Set up the checkpointing system for the Opey agent.
    """
    # Check if the environment variable is set to enable checkpointing
    async with AsyncSqliteSaver.from_conn_string('checkpoints.db') as checkpointer:
        yield checkpointer

class OpeyContext:
    """
    Class to manage Opey sessions.
    """
    def __init__(self, session_data: Annotated[SessionData, Depends(session_verifier)], checkpointer: Annotated[AsyncSqliteSaver, Depends(setup_checkpointing)]):
        self.consent_jwt = session_data.consent_jwt

        if os.getenv("DISABLE_OBP_CALLING") == "true":
            logger.info("Disabling OBP tools: Calls to the OBP-API will not be available")
            self.graph = opey_graph_no_obp_tools
        else:
            logger.info("Enabling OBP tools: Calls to the OBP-API will be available")
            self.graph = opey_graph

        # Assign the checkpointer
        self.graph.checkpointer = checkpointer

        