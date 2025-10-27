from pydantic import BaseModel, Field
from typing import Dict, Any
from typing import Optional
from datetime import datetime

class SessionData(BaseModel):
    consent_jwt: Optional[str] = None
    is_anonymous: bool = False
    token_usage: int = 0
    request_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now, description="Timestamp when the session was created")
    last_accessed: datetime = Field(default_factory=datetime.now, description="Timestamp when the session was last accessed")
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata for the session")

    def update_last_accessed(self):

        self.last_accessed = datetime.now()

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        return (datetime.now() - self.last_accessed).total_seconds() > timeout_minutes * 60
    

    