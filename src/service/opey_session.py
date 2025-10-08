from typing import Annotated

from auth.session import session_verifier, SessionData, session_cookie
from auth.auth import OBPConsentAuth
from auth.usage_tracker import usage_tracker
from fastapi import Depends, Request
from uuid import UUID

from agent.graph_builder import OpeyAgentGraphBuilder, create_basic_opey_graph, create_supervised_opey_graph
from agent.components.tools import endpoint_retrieval_tool, glossary_retrieval_tool

from agent.utils.obp import OBPRequestsModule
from service.checkpointer import get_global_checkpointer
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.runnables.graph import MermaidDrawMethod


import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('opey.session')

class OpeySession:
    """
    Class to manage Opey sessions.
    Depends first on the authentication layer, i.e. session_verifier
    """
    def __init__(self, request: Request, session_data: Annotated[SessionData, Depends(session_verifier)], session_id: Annotated[UUID, Depends(session_cookie)], checkpointer: Annotated[BaseCheckpointSaver, Depends(get_global_checkpointer)]):
        # Store session data and check usage limits for anonymous sessions
        self.session_data = session_data
        self.session_id = session_id
        # Note: Usage limits will be checked when methods are called

        # Store session data in request state for middleware to update
        request.state.session_data = session_data
        request.state.session_id = session_id

        # Get consent_jwt from the session data (None for anonymous sessions)
        self.consent_jwt = session_data.consent_jwt
        self.is_anonymous = session_data.is_anonymous
        
        # Set up the model used
        self._setup_model()
        
        # Initialize auth object only if not anonymous
        if not self.is_anonymous:
            self.auth = OBPConsentAuth(consent_jwt=self.consent_jwt)

        obp_api_mode = os.getenv("OBP_API_MODE")

        # For anonymous sessions, limit to SAFE or NONE modes only
        if self.is_anonymous and obp_api_mode in ["DANGEROUS", "TEST"]:
            logger.warning(f"Anonymous session attempted to use {obp_api_mode} mode. Defaulting to SAFE mode.")
            obp_api_mode = "SAFE"

        if obp_api_mode != "NONE" and not self.is_anonymous:
            # Initialize the OBPRequestsModule with the auth object (only for authenticated sessions)
            self.obp_requests = OBPRequestsModule(self.auth)

        # Base tools that all modes should have:
        base_tools = [endpoint_retrieval_tool, glossary_retrieval_tool]
        # Initialize the graph with the appropriate tools based on the OBP API mode
        match obp_api_mode:
            case "NONE":
                logger.info("OBP API mode set to NONE: Calls to the OBP-API will not be available")
                self.graph = (OpeyAgentGraphBuilder()
                              .with_tools(base_tools)
                              .with_model(self._model_name, temperature=0.5)
                              .with_checkpointer(checkpointer)
                              .enable_human_review(False)
                              .build())

            case "SAFE":
                if self.is_anonymous:
                    logger.info("Anonymous session using SAFE mode: Only GET requests to OBP-API will be available")
                    prompt_addition = "Note: This is an anonymous session with limited capabilities. User can only make GET requests to the OBP-API. Ensure all responses adhere to this restriction."
                    self.graph = (OpeyAgentGraphBuilder()
                                 .with_tools(base_tools)
                                 .with_model(self._model_name, temperature=0.5)
                                 .add_to_system_prompt(prompt_addition)
                                 .with_checkpointer(checkpointer)
                                 .enable_human_review(False)
                                 .build())
                else:
                    logger.info("OBP API mode set to SAFE: GET requests to the OBP-API will be available")
                    tools = base_tools + [self.obp_requests.get_langchain_tool('safe')]
                    self.graph = (OpeyAgentGraphBuilder()
                                 .with_tools(tools)
                                 .with_model(self._model_name, temperature=0.5)
                                 .with_checkpointer(checkpointer)
                                 .enable_human_review(False)
                                 .build())

            case "DANGEROUS":
                logger.info("OBP API mode set to DANGEROUS: All requests to the OBP-API will be available subject to user approval.")
                tools = base_tools + [self.obp_requests.get_langchain_tool('dangerous')]
                self.graph = (OpeyAgentGraphBuilder()
                             .with_tools(tools)
                             .with_model(self._model_name, temperature=0.5)
                             .with_checkpointer(checkpointer)
                             .enable_human_review(True)
                             .build())

            case "TEST":
                logger.info("OBP API mode set to TEST: All requests to the OBP-API will be available AND WILL BE APPROVED BY DEFAULT.")
                tools = base_tools + [self.obp_requests.get_langchain_tool('test')]
                test_prompt = "You are in TEST mode. Operations will be auto-approved. DO NOT USE IN PRODUCTION."
                self.graph = (OpeyAgentGraphBuilder()
                             .with_tools(tools)
                             .add_to_system_prompt(test_prompt)
                             .with_model(self._model_name, temperature=0.5)  # Example: use larger model in test
                             .with_checkpointer(checkpointer)
                             .enable_human_review(False)
                             .build())

            case _:
                logger.error(f"OBP API mode set to {obp_api_mode}: Unknown OBP API mode. Defaulting to NONE.")
                self.graph = create_basic_opey_graph(base_tools)
                self.graph.checkpointer = checkpointer


        self.graph.checkpointer = checkpointer
        
    def _setup_model(self):
        """
        Set up the model for the session.
        """
        from agent.utils.model_factory import LLMProviders, get_available_models
        model_provider = os.getenv("MODEL_PROVIDER")
        if not model_provider:
            raise ValueError("MODEL_PROVIDER environment variable must be set")
        
        if not (model_provider := model_provider.lower()) in [provider.value for provider in LLMProviders]:
            raise ValueError(f"Unsupported MODEL_PROVIDER: {model_provider}. Supported providers: {[provider.value for provider in LLMProviders]}")
        
        try:
            
            available_models = get_available_models(LLMProviders(model_provider))
        except RuntimeError as e:
            logger.error(f"Error checking available models: {e}")
            raise
        
        logger.info(f"Using model provider: {model_provider}")
        logger.info(f"Available models for provider {model_provider}: {available_models}")
        
        model_name = os.getenv("MODEL_NAME")
        if not model_name:
            raise ValueError("MODEL_NAME environment variable must be set")
        
        if model_name not in available_models:
            raise ValueError(f"MODEL_NAME {model_name} is not available for provider {model_provider}. Available models: {available_models}")
        
        logger.info(f"Using model: {model_name}")
        self._model_name = model_name
        
        
        
        
        
        
        
        
        
        
        
        

    def update_token_usage(self, token_count: int) -> None:
        """
        Update token usage for the session.

        Args:
            token_count: Number of tokens used
        """
        if self.is_anonymous:
            usage_tracker.update_token_usage(self.session_data, token_count)

    def update_request_count(self) -> None:
        """
        Update request count for the session.
        """
        if self.is_anonymous:
            usage_tracker.update_request_count(self.session_data)

    def get_usage_info(self) -> dict:
        """
        Get usage information for the session.

        Returns:
            Dictionary containing usage information
        """
        return usage_tracker.get_usage_info(self.session_data)

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
