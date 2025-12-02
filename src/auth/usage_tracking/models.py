from enum import Enum
from pydantic import BaseModel
from typing import Dict

class UserTier(str, Enum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED_FREE = "authenticated_free"
    AUTHENTICATED_PREMIUM = "authenticated_premium"
    

class TierLimits(BaseModel):
    """Defines the usage limits for a specific user tier."""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    cost_per_day_usd: float
    
class UsageRecord(BaseModel):
    """Usage for a specific user."""
    total_requests: int
    total_cost_usd: float
    total_tokens: int