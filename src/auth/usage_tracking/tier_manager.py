from typing import Optional
import logging
from datetime import datetime
from ..admin_client import get_admin_client
from client.obp_client import OBPClient
from .models import UserTier

logger = logging.getLogger(__name__)

class TierManager:
    """
    Manages user tier assignments for Opey usage tracking.
    Uses non-personal user attributes on OBP.
    """
    def __init__(self, obp_client: OBPClient):
        self.obp_client = obp_client
        
    async def assign_tier(self, user_id: str, tier: UserTier) -> None:
        """
        Assign a tier to a user by updating their non-personal attributes.
        """
        