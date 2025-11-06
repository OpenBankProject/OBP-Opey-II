from pydantic import BaseModel, Field
from typing import Optional, Any
from langchain_core.messages import BaseMessage
from uuid import UUID

class Thread(BaseModel):
    id: UUID = Field(..., description="Unique identifier for the thread")
    title: str = Field(..., description="Title of the thread")
    messages: list[BaseMessage] = Field(..., description="List of messages in the thread")
    created_at: str = Field(..., description="Creation timestamp of the thread")
    updated_at: Optional[str] = Field(None, description="Last updated timestamp of the thread")
    metadata: Optional[dict[str, Any]] = Field(None, description="Additional metadata for the thread")
    