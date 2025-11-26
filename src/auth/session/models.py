# Set up sessions to use consents
from pydantic import BaseModel
from typing import Optional

class SessionData(BaseModel):
    consent_id: Optional[str] = None
    is_anonymous: bool = False
    token_usage: int = 0
    request_count: int = 0
    user_id: Optional[str] = None