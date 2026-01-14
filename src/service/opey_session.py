from typing import Annotated

from auth.session import session_verifier, SessionData, session_cookie
from auth.auth import OBPConsentAuth
from auth.usage_tracker import usage_tracker
from fastapi import Depends, Request
from uuid import UUID

from agent.graph_builder import OpeyAgentGraphBuilder, create_basic_opey_graph, create_supervised_opey_graph
from agent.components.tools import endpoint_retrieval_tool, glossary_retrieval_tool
from agent.components.tools import get_tool_registry, create_approval_manager
from agent.components.tools.approval_models import (
    ToolApprovalMetadata, ApprovalPattern, ApprovalAction,
    RiskLevel, ApprovalLevel
)

from client.obp_client import OBPClient
from service.checkpointer_registry import get_global_checkpointer
from service.redis_client import get_redis_client
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.runnables.graph import MermaidDrawMethod


import os
import logging
import json

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

        # Get consent_id from the session data (None for anonymous sessions)
        self.consent_id = session_data.consent_id
        self.is_anonymous = session_data.is_anonymous
        
        # Set up the model used
        self._setup_model()
        
        # Initialize approval system
        self.tool_registry = get_tool_registry()
        redis_client = get_redis_client() if os.getenv("REDIS_URL") else None
        workspace_config = self._load_workspace_approval_config()
        self.approval_manager = create_approval_manager(
            redis_client=redis_client,
            workspace_config=workspace_config
        )
        
        # Initialize auth object only if not anonymous
        if not self.is_anonymous:
            self.auth = OBPConsentAuth(consent_id=self.consent_id)

        obp_api_mode = os.getenv("OBP_API_MODE")

        # For anonymous sessions, limit to SAFE or NONE modes only
        if self.is_anonymous and obp_api_mode in ["DANGEROUS", "TEST"]:
            logger.warning(f"Anonymous session attempted to use {obp_api_mode} mode. Defaulting to SAFE mode.")
            obp_api_mode = "SAFE"

        if obp_api_mode != "NONE" and not self.is_anonymous:
            # Initialize the OBPClient with the auth object (only for authenticated sessions)
            self.obp_requests = OBPClient(self.auth)

        # Register base tools with approval metadata
        self._register_base_tools()
        
        # Register OBP tools if needed
        if obp_api_mode != "NONE" and not self.is_anonymous:
            self._register_obp_tools(obp_api_mode)
        
        # Get tools from registry
        base_tools = self.tool_registry.get_langchain_tools()
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
                    self.graph = (OpeyAgentGraphBuilder()
                                 .with_tools(base_tools)
                                 .with_model(self._model_name, temperature=0.5)
                                 .with_checkpointer(checkpointer)
                                 .enable_human_review(False)
                                 .build())

            case "DANGEROUS":
                logger.info("OBP API mode set to DANGEROUS: All requests to the OBP-API will be available subject to user approval.")
                self.graph = (OpeyAgentGraphBuilder()
                             .with_tools(base_tools)
                             .with_model(self._model_name, temperature=0.5)
                             .with_checkpointer(checkpointer)
                             .enable_human_review(True)
                             .build())

            case "TEST":
                logger.info("OBP API mode set to TEST: All requests to the OBP-API will be available AND WILL BE APPROVED BY DEFAULT.")
                test_prompt = "You are in TEST mode. Operations will be auto-approved. DO NOT USE IN PRODUCTION."
                self.graph = (OpeyAgentGraphBuilder()
                             .with_tools(base_tools)
                             .add_to_system_prompt(test_prompt)
                             .with_model(self._model_name, temperature=0.5)
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
    
    def _load_workspace_approval_config(self) -> dict:
        """
        Load workspace-level approval configuration.
        Could be from environment, config file, or database.
        """
        # Try to load from environment variable first
        config_str = os.getenv("WORKSPACE_APPROVAL_CONFIG", "{}")
        try:
            config = json.loads(config_str)
            if config:
                logger.info(f"Loaded workspace approval config from environment")
            return config
        except json.JSONDecodeError:
            logger.warning("Invalid WORKSPACE_APPROVAL_CONFIG JSON, using empty config")
            return {}
    
    def _register_base_tools(self):
        """Register base tools (endpoint_retrieval, glossary_retrieval) with approval metadata"""
        self.tool_registry.register_tool(
            tool=endpoint_retrieval_tool,
            approval_metadata=ToolApprovalMetadata(
                tool_name="endpoint_retrieval_tool",
                description="Retrieve OBP API endpoint documentation",
                requires_auth=False,
                default_risk_level=RiskLevel.SAFE,
                patterns=[
                    ApprovalPattern(
                        method="*",
                        path="*",
                        action=ApprovalAction.AUTO_APPROVE,
                        reason="Read-only operation"
                    )
                ],
                can_be_pre_approved=True,
                available_approval_levels=[ApprovalLevel.ONCE, ApprovalLevel.SESSION]
            )
        )
        
        self.tool_registry.register_tool(
            tool=glossary_retrieval_tool,
            approval_metadata=ToolApprovalMetadata(
                tool_name="glossary_retrieval_tool",
                description="Retrieve glossary definitions",
                requires_auth=False,
                default_risk_level=RiskLevel.SAFE,
                patterns=[
                    ApprovalPattern(
                        method="*",
                        path="*",
                        action=ApprovalAction.AUTO_APPROVE,
                        reason="Read-only operation"
                    )
                ],
                can_be_pre_approved=True,
                available_approval_levels=[ApprovalLevel.ONCE, ApprovalLevel.SESSION]
            )
        )
        logger.info("Registered base tools with approval metadata")
    
    def _register_obp_tools(self, obp_api_mode: str):
        """Register OBP tools with approval metadata based on mode"""
        if obp_api_mode == "SAFE":
            # Only GET requests, auto-approve
            patterns = [
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="SAFE mode: read-only operations"
                )
            ]
        elif obp_api_mode == "DANGEROUS":
            # GET auto-approved, others require approval
            patterns = [
                ApprovalPattern(
                    method="GET",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="Read-only operation"
                ),
                ApprovalPattern(
                    method="POST",
                    path="/obp/*/accounts/*/views",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="View creation is low risk"
                ),
                ApprovalPattern(
                    method="DELETE",
                    path="/obp/*/banks/*",
                    action=ApprovalAction.ALWAYS_DENY,
                    reason="Cannot delete banks"
                ),
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.REQUIRE_APPROVAL,
                    reason="Default: require approval for modifications"
                )
            ]
        else:  # TEST mode
            patterns = [
                ApprovalPattern(
                    method="*",
                    path="*",
                    action=ApprovalAction.AUTO_APPROVE,
                    reason="TEST mode: auto-approve everything"
                )
            ]
        
        # Cast to proper literal type for get_langchain_tool
        mode = obp_api_mode.lower()
        if mode not in ("safe", "dangerous", "test"):
            raise ValueError(f"Invalid OBP API mode: {obp_api_mode}")
        
        obp_tool = self.obp_requests.get_langchain_tool(mode)  # type: ignore
        
        self.tool_registry.register_tool(
            tool=obp_tool,
            approval_metadata=ToolApprovalMetadata(
                tool_name="obp_requests",
                description="Make HTTP requests to OBP API",
                requires_auth=True,
                default_risk_level=RiskLevel.DANGEROUS,
                patterns=patterns,
                can_be_pre_approved=True,
                available_approval_levels=[
                    ApprovalLevel.ONCE,
                    ApprovalLevel.SESSION,
                    ApprovalLevel.USER
                ]
            )
        )
        logger.info(f"Registered OBP tools for {obp_api_mode} mode with approval metadata")

    def build_config(self, base_config: dict | None = None) -> dict:
        """
        Build a complete RunnableConfig by merging base session config with runtime config.
        This ensures model context is available to all nodes without clashing with
        service-level config like thread_id.
        
        Args:
            base_config: Optional config dict from service endpoints (e.g., with thread_id)
        
        Returns:
            Merged config dict with all necessary context
        
        Example:
            # In service.py:
            config = opey_session.build_config({'configurable': {'thread_id': thread_id}})
        """
        base_config = base_config or {}
        
        # Session-level configuration (model context, approval manager, consent_id)
        session_configurable = {
            "model_name": self._model_name,
            "model_kwargs": {},  # Add model_kwargs if needed in future
            "approval_manager": self.approval_manager,
        }
        
        # Add consent_id for checkpoint operations if user is authenticated
        # This is JSON-serializable unlike the OBPClient object
        if not self.is_anonymous and self.consent_id:
            session_configurable["consent_id"] = self.consent_id
        
        # Merge: base config takes precedence for runtime values like thread_id
        merged_configurable = {
            **session_configurable,
            **base_config.get("configurable", {})
        }
        
        return {
            **base_config,
            "configurable": merged_configurable
        }

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
