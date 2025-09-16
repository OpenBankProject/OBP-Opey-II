import time
import logging
from typing import Dict, Optional

from .processors import StreamEventOrchestrator
from schema import StreamInput

logger = logging.getLogger(__name__)

class OrchestratorRepository:
    """Repository for managing StreamEventOrchestrator instances"""
    
    def __init__(self):
        self._orchestrators: Dict[str, StreamEventOrchestrator] = {}
        self._last_access: Dict[str, float] = {}
    
    def get_or_create(self, thread_id: str, stream_input: StreamInput) -> StreamEventOrchestrator:
        """Get existing orchestrator or create a new one if it doesn't exist"""
        if thread_id not in self._orchestrators:
            logger.info(f"Creating new StreamEventOrchestrator for thread_id {thread_id}")
            self._orchestrators[thread_id] = StreamEventOrchestrator(stream_input)
        else:
            logger.info(f"Reusing existing StreamEventOrchestrator for thread_id {thread_id}")
        
        # Update last access time
        self._last_access[thread_id] = time.time()
        return self._orchestrators[thread_id]
    
    def cleanup_inactive(self, max_age_seconds: int = 3600) -> int:
        """Remove orchestrators that have been inactive for a certain time"""
        current_time = time.time()
        to_remove = [thread_id for thread_id, last_access in self._last_access.items()
                    if current_time - last_access > max_age_seconds]
        
        for thread_id in to_remove:
            logger.info(f"Cleaning up inactive orchestrator for thread_id {thread_id}")
            del self._orchestrators[thread_id]
            del self._last_access[thread_id]
        
        return len(to_remove)

# Create singleton instance - still avoids repeated instantiation but more controlled
# than naked globals
orchestrator_repository = OrchestratorRepository()