from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class GlossaryDocumentSchema:
    """Schema for glossary documents in the vector store"""
    title: str
    description: str
    type: str = "glossary_item"
    index: int = 0  # Used to differentiate duplicates
    
    def to_document_content(self) -> str:
        """Convert schema to document content format"""
        return f"Title: {self.title}\nDescription: {self.description}"
    
    def to_metadata(self) -> Dict[str, Any]:
        """Convert schema to document metadata"""
        # Keep original casing, only replace spaces; append index if duplicate
        base_id = self.title.replace(" ", "_")
        doc_id = f"{base_id}_{self.index}" if self.index > 0 else base_id
        return {
            "document_id": doc_id,
            "title": self.title,
            "type": self.type
        }
    
    @classmethod
    def from_document(cls, content: str, metadata: Dict[str, Any]) -> "GlossaryDocumentSchema":
        """Create schema instance from document content and metadata"""
        # Extract title and description from content
        lines = content.strip().split("\n", 2)
        title = lines[0].replace("Title: ", "") if len(lines) > 0 else ""
        description = lines[1].replace("Description: ", "") if len(lines) > 1 else ""
        
        return cls(
            title=metadata.get("title", title),
            description=description,
            type=metadata.get("type", "glossary_item")
        )


@dataclass
class EndpointDocumentSchema:
    """Schema for API endpoint documents in the vector store"""
    path: str
    method: str
    operation_id: str
    details: Dict[str, Any]
    tags: List[str] = field(default_factory=list)
    
    def to_document_content(self) -> str:
        """Convert schema to document content format (full version for final output)."""
        import json
        # Format matching the original script's structure
        path_content = {self.path: {self.method.lower(): self.details}}
        return json.dumps(path_content)
    
    def to_grading_content(self) -> str:
        """
        Convert schema to compact format for LLM grading (token-efficient).
        
        Extracts only the fields needed for relevance assessment:
        - summary, description (truncated), tags, parameters overview
        """
        import re
        
        summary = self.details.get("summary", "")
        description = self.details.get("description", "")
        
        # Strip HTML tags and truncate description
        description_clean = re.sub(r'<[^>]+>', ' ', description)
        description_clean = re.sub(r'\s+', ' ', description_clean).strip()
        # Keep first 200 chars of description for context
        if len(description_clean) > 200:
            description_clean = description_clean[:200] + "..."
        
        # Extract parameter names only (not full schemas)
        params = self.details.get("parameters", [])
        param_names = [p.get("name", "") for p in params if isinstance(p, dict) and p.get("in") != "body"]
        
        # Build compact representation
        parts = [
            f"{self.method.upper()} {self.path}",
            f"Summary: {summary}" if summary else "",
            f"Tags: {', '.join(self.tags)}" if self.tags else "",
            f"Description: {description_clean}" if description_clean else "",
            f"Parameters: {', '.join(param_names)}" if param_names else "",
        ]
        return "\n".join(p for p in parts if p)
    
    def to_metadata(self) -> Dict[str, Any]:
        """Convert schema to document metadata"""
        
        metadata = {
            # Use operation_id as document_id since it's guaranteed unique per endpoint
            "document_id": self.operation_id,
            "method": self.method.upper(),
            "operation_id": self.operation_id,
            "path": self.path,
            "tags": ", ".join(self.tags) if self.tags else "",
            # Store summary in metadata for quick access without parsing page_content
            "summary": self.details.get("summary", ""),
        }
            
        return metadata
    
    @classmethod
    def from_document(cls, content: str, metadata: Dict[str, Any]) -> "EndpointDocumentSchema":
        """Create schema instance from document content and metadata"""
        import json
        
        # Extract data from content (JSON string)
        try:
            content_data = json.loads(content)
            path = next(iter(content_data))
            method = next(iter(content_data[path]))
            details = content_data[path][method]
        except (json.JSONDecodeError, StopIteration):
            path = metadata.get("path", "")
            method = metadata.get("method", "").lower()
            details = {}
        
        # Extract tags from metadata
        tags_str = metadata.get("tags", "")
        tags = [tag.strip() for tag in tags_str.split(",")] if tags_str else []
        
        return cls(
            path=metadata.get("path", path),
            method=metadata.get("method", method.upper()),
            operation_id=metadata.get("operation_id", ""),
            details=details,
            tags=tags
        )