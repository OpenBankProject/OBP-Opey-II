"""
Cancellation Manager for LangGraph Streaming

Provides cooperative cancellation support for long-running streaming operations.
Since LangGraph doesn't support native mid-stream cancellation, this manager
uses a shared state approach where nodes periodically check for cancellation flags.
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CancellationManager:
    """
    Manages cancellation state for streaming operations.
    
    This is a cooperative cancellation system - nodes must explicitly check
    the cancellation state and decide how to handle it.
    
    Thread-safe for async operations.
    """
    
    def __init__(self):
        self._cancellations: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
    
    async def request_cancellation(self, thread_id: str) -> None:
        """
        Mark a thread for cancellation.
        
        Args:
            thread_id: The thread/conversation ID to cancel
        """
        async with self._lock:
            self._cancellations[thread_id] = datetime.now()
            logger.info(f"Cancellation requested for thread: {thread_id}")
    
    async def is_cancelled(self, thread_id: str) -> bool:
        """
        Check if a thread has been marked for cancellation.
        
        Args:
            thread_id: The thread/conversation ID to check
            
        Returns:
            True if cancellation was requested, False otherwise
        """
        async with self._lock:
            is_cancelled = thread_id in self._cancellations
            if is_cancelled:
                logger.debug(f"Thread {thread_id} is marked for cancellation")
            return is_cancelled
    
    async def clear_cancellation(self, thread_id: str) -> None:
        """
        Remove cancellation flag after handling.
        
        This should be called after the cancellation has been processed
        to prevent future operations from being incorrectly cancelled.
        
        Args:
            thread_id: The thread/conversation ID to clear
        """
        async with self._lock:
            if thread_id in self._cancellations:
                del self._cancellations[thread_id]
                logger.info(f"Cancellation flag cleared for thread: {thread_id}")
    
    async def cleanup_old_flags(self, max_age_minutes: int = 10) -> int:
        """
        Remove stale cancellation flags.
        
        This prevents memory leaks from abandoned cancellations.
        Should be called periodically (e.g., every few minutes).
        
        Args:
            max_age_minutes: Remove flags older than this many minutes
            
        Returns:
            Number of flags removed
        """
        async with self._lock:
            cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
            to_remove = [
                tid for tid, timestamp in self._cancellations.items()
                if timestamp < cutoff
            ]
            
            for tid in to_remove:
                del self._cancellations[tid]
            
            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} stale cancellation flags")
            
            return len(to_remove)
    
    async def get_active_cancellations(self) -> list[str]:
        """
        Get list of all threads with active cancellation flags.
        
        Useful for debugging and monitoring.
        
        Returns:
            List of thread IDs with active cancellations
        """
        async with self._lock:
            return list(self._cancellations.keys())
    
    async def get_stats(self) -> dict:
        """
        Get statistics about cancellation state.
        
        Returns:
            Dictionary with statistics
        """
        async with self._lock:
            return {
                "active_cancellations": len(self._cancellations),
                "thread_ids": list(self._cancellations.keys()),
                "oldest_flag": min(self._cancellations.values()) if self._cancellations else None,
                "newest_flag": max(self._cancellations.values()) if self._cancellations else None,
            }


# Global singleton instance
cancellation_manager = CancellationManager()