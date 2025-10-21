from langchain_core.tools import BaseTool
from typing import Dict, Callable, Optional, Literal, List
import fnmatch
import logging

from .approval_models import (
    ToolApprovalMetadata, ApprovalPattern, ApprovalAction,
    RiskLevel, ApprovalLevel, ApprovalContext
)

logger = logging.getLogger(__name__)

class RegisteredTool:
    """Container for a tool and its approval metadata"""
    
    def __init__(self, tool: BaseTool, metadata: ToolApprovalMetadata,):
        self.tool = tool
        self.metadata = metadata
        
    def should_require_approval(self, tool_args: Dict) -> bool:
        """
        Check if this tool requires user approval.
        """
        # First check custom approval logic if provided
        if self.metadata.custom_approval_checker:
            return self.metadata.custom_approval_checker(tool_args)
        
        # Otherwise check patterns
        for pattern in self.metadata.patterns:
            if self._matches_pattern(tool_args, pattern):
                if pattern.action == ApprovalAction.AUTO_APPROVE:
                    return False
                elif pattern.action == ApprovalAction.ALWAYS_DENY:
                    raise ValueError(f"Tool call denied by pattern: {pattern}")
                elif pattern.action == ApprovalAction.REQUIRE_APPROVAL:
                    return True
        
        # Default behaviour based on risk level
        return self.metadata.default_risk_level in [RiskLevel.DANGEROUS, RiskLevel.CRITICAL]
    
    def _matches_pattern(self, tool_args: Dict, pattern: ApprovalPattern):
        """Check if tool args match approval pattern"""
        # Match method
        if pattern.method != "*":
            actual_method = tool_args.get("method", "").upper()
            if actual_method != pattern.method.upper():
                return False
            
        # Match path
        if pattern.path != "*":
            actual_path = tool_args.get("path", "")
            if not fnmatch.fnmatch(actual_path, pattern.path):
                return False
            
        return True
    
    def build_approval_context(
        self, 
        tool_call_id: str,
        tool_args: Dict,
        session_history: Optional[Dict] = None
    ) -> ApprovalContext:
        "Build a rich, imformative approval context for a tool call"
        
        # Use custom context builder if provided
        if self.metadata.custom_context_builder:
            custom_context = self.metadata.custom_context_builder(tool_args)
        else:
            custom_context = {}
            
        # Build summary of the operation
        operation_summary = self._generate_summary(tool_args)
        
        # Dynamically assess the risk level
        # Could use a small LLM to do this later
        risk_level = self._assess_risk(tool_args)
        
        # Count similar operations from the session history
        similar_count = 0
        last_similar = None
        if session_history:
            similar_count = session_history.get("similar_count", 0)
            last_similar = session_history.get("last_similar_approval")
            
        return ApprovalContext(
            tool_name=self.tool.name,
            tool_call_id=tool_call_id,
            tool_input=tool_args,
            operation_summary=operation_summary,
            message=custom_context.get("message", f"Approve {operation_summary}?"),
            risk_level=risk_level,
            affected_resources=custom_context.get("affected_resources", []),
            reversible=custom_context.get("reversible", True),
            estimated_impact=custom_context.get("estimated_impact", ""),
            similar_operations_count=similar_count,
            last_similar_approval=last_similar,
            available_approval_levels=self.metadata.available_approval_levels,
            default_approval_level=ApprovalLevel.ONCE if risk_level == RiskLevel.CRITICAL else ApprovalLevel.SESSION
        )
    
    def _generate_summary(self, tool_args: Dict) -> str:
        """Generate a human-readable summary of the operation"""
        if self.tool.name == "obp_requests":
            
            method = tool_args.get("method", "UNKNOWN").upper()
            path = tool_args.get("path", "/unknown/path")
            return f"{method} request to {path}"
        
        return f"Execute {self.tool.name}"
    
    def _assess_risk(self, tool_args: Dict) -> RiskLevel:
        """Dynamically assess risk level based on tool args"""
        if self.tool.name == "obp_requests":
            method = tool_args.get("method", "").upper()
            
            if method == "GET":
                return RiskLevel.SAFE
            elif method == "POST":
                # NOTE: Can be made more sophisticated by checking the path
                
                # if "/banks/" in tool_args.get("path", ""):
                #     return RiskLevel.CRITICAL
                return RiskLevel.DANGEROUS
            elif method in ["PUT", "PATCH"]:
                return RiskLevel.DANGEROUS
            elif method == "DELETE":
                return RiskLevel.CRITICAL
            
            
        return self.metadata.default_risk_level
    
class ToolRegistry:
    """
    Centralized registry for managing tools and their approval metadata.
    Source of truth for all tools available to the agent.
    TODO: Support MCP tools through a separate registry and conversion into langgchain tools
    """
    
    def __init__(self):
        self._tools: Dict[str, RegisteredTool] = {}
        logger.info("Initialized ToolRegistry")
        
    def register_tool(self, tool: BaseTool, approval_metadata: ToolApprovalMetadata) -> None:
        """Register a new tool with its approval metadata"""
        if tool.name in self._tools:
            logger.warning(f"Tool {tool.name} is already registered, overwriting.")
        
        self._tools[tool.name] = RegisteredTool(tool, approval_metadata)
        logger.info(f"Registered tool: {tool.name} with approval metadata: {approval_metadata}")
        
    def get_tool(self, name: str) -> Optional[RegisteredTool]:
        """Retrieve a registered tool by name"""
        return self._tools.get(name)
    
    def get_langchain_tools(self) -> List[BaseTool]:
        """Get list of LangChain tools for binding to a graph"""
        return [rt.tool for rt in self._tools.values()]
    
    def should_require_approval(self, tool_name: str, tool_args: Dict) -> bool:
        """Check if a tool requires approval for given args"""
        registered_tool = self._tools.get(tool_name)
        if not registered_tool:
            logger.warning(f"Unknown tool {tool_name}, assuming that approval is needed.")
            return True
        
        return registered_tool.should_require_approval(tool_args)
    
    def build_approval_context(
        self,
        tool_name: str,
        tool_call_id: str,
        tool_args: Dict,
        session_history: Optional[Dict] = None
    ) -> ApprovalContext:
        """Build approval context for a tool call"""
        registered_tool = self._tools.get(tool_name)
        if not registered_tool:
            # Fallback context for unknown tools
            logger.warning(f"Unknown tool {tool_name}, building generic approval context.")
            return ApprovalContext(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_input=tool_args,
                operation_summary=f"Execute unknown tool {tool_name}",
                message=f"Approve execution of {tool_name}?",
                risk_level=RiskLevel.MODERATE,
                available_approval_levels=[ApprovalLevel.ONCE, ApprovalLevel.SESSION],
            )
        
        return registered_tool.build_approval_context(
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            session_history=session_history
        )
        
    def get_tool_metadata(self, tool_name: str) -> Optional[ToolApprovalMetadata]:
        """Get approval metadata for a registered tool"""
        registered_tool = self._tools.get(tool_name)
        if not registered_tool:
            return None
        return registered_tool.metadata
        