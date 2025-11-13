from typing import Optional
from auth.session.models import SessionData
from auth.usage_tracking.models import UserTier
import logging

logger = logging.getLogger(__name__)

class UserTierResolver:
    """
    Resolves user tier based on consent_id or session data
    """