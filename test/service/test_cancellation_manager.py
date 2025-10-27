"""
Tests for the streaming cancellation manager.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from utils.cancellation_manager import CancellationManager, cancellation_manager


class TestCancellationManager:
    """Test suite for CancellationManager"""
    
    @pytest.fixture
    async def manager(self):
        """Create a fresh manager for each test"""
        manager = CancellationManager()
        yield manager
        # Clean up after test
        await manager.cleanup_old_flags(max_age_minutes=0)
    
    @pytest.mark.asyncio
    async def test_request_cancellation(self, manager):
        """Test requesting cancellation for a thread"""
        thread_id = "test-thread-123"
        
        # Initially not cancelled
        assert not await manager.is_cancelled(thread_id)
        
        # Request cancellation
        await manager.request_cancellation(thread_id)
        
        # Should now be cancelled
        assert await manager.is_cancelled(thread_id)
    
    @pytest.mark.asyncio
    async def test_clear_cancellation(self, manager):
        """Test clearing a cancellation flag"""
        thread_id = "test-thread-456"
        
        # Set up cancellation
        await manager.request_cancellation(thread_id)
        assert await manager.is_cancelled(thread_id)
        
        # Clear it
        await manager.clear_cancellation(thread_id)
        assert not await manager.is_cancelled(thread_id)
    
    @pytest.mark.asyncio
    async def test_multiple_threads(self, manager):
        """Test managing cancellations for multiple threads"""
        thread1 = "thread-1"
        thread2 = "thread-2"
        thread3 = "thread-3"
        
        # Cancel first two
        await manager.request_cancellation(thread1)
        await manager.request_cancellation(thread2)
        
        # Check states
        assert await manager.is_cancelled(thread1)
        assert await manager.is_cancelled(thread2)
        assert not await manager.is_cancelled(thread3)
        
        # Get active list
        active = await manager.get_active_cancellations()
        assert len(active) == 2
        assert thread1 in active
        assert thread2 in active
    
    @pytest.mark.asyncio
    async def test_cleanup_old_flags(self, manager):
        """Test cleanup of stale cancellation flags"""
        thread_old = "thread-old"
        thread_new = "thread-new"
        
        # Set up cancellations
        await manager.request_cancellation(thread_old)
        await manager.request_cancellation(thread_new)
        
        # Manually age one of them
        async with manager._lock:
            manager._cancellations[thread_old] = datetime.now() - timedelta(minutes=15)
        
        # Clean up flags older than 10 minutes
        removed = await manager.cleanup_old_flags(max_age_minutes=10)
        
        # Should have removed the old one
        assert removed == 1
        assert not await manager.is_cancelled(thread_old)
        assert await manager.is_cancelled(thread_new)
    
    @pytest.mark.asyncio
    async def test_get_stats(self, manager):
        """Test getting statistics about cancellations"""
        # Empty state
        stats = await manager.get_stats()
        assert stats["active_cancellations"] == 0
        assert stats["oldest_flag"] is None
        
        # Add some cancellations
        await manager.request_cancellation("thread-1")
        await asyncio.sleep(0.1)  # Ensure different timestamps
        await manager.request_cancellation("thread-2")
        
        # Check stats
        stats = await manager.get_stats()
        assert stats["active_cancellations"] == 2
        assert stats["oldest_flag"] is not None
        assert stats["newest_flag"] is not None
        assert stats["oldest_flag"] < stats["newest_flag"]
    
    @pytest.mark.asyncio
    async def test_concurrent_access(self, manager):
        """Test thread-safe concurrent access"""
        thread_ids = [f"thread-{i}" for i in range(10)]
        
        # Request cancellations concurrently
        await asyncio.gather(*[
            manager.request_cancellation(tid)
            for tid in thread_ids
        ])
        
        # All should be cancelled
        for tid in thread_ids:
            assert await manager.is_cancelled(tid)
        
        # Clear them concurrently
        await asyncio.gather(*[
            manager.clear_cancellation(tid)
            for tid in thread_ids
        ])
        
        # None should be cancelled
        for tid in thread_ids:
            assert not await manager.is_cancelled(tid)
    
    @pytest.mark.asyncio
    async def test_idempotent_operations(self, manager):
        """Test that operations are idempotent"""
        thread_id = "test-thread"
        
        # Request cancellation multiple times
        await manager.request_cancellation(thread_id)
        await manager.request_cancellation(thread_id)
        await manager.request_cancellation(thread_id)
        
        # Should still work
        assert await manager.is_cancelled(thread_id)
        
        # Clear multiple times
        await manager.clear_cancellation(thread_id)
        await manager.clear_cancellation(thread_id)
        
        # Should still work
        assert not await manager.is_cancelled(thread_id)


class TestGlobalCancellationManager:
    """Test the global singleton instance"""
    
    @pytest.mark.asyncio
    async def test_global_instance(self):
        """Test that the global instance works"""
        from utils.cancellation_manager import (
            request_cancellation,
            is_cancelled,
            clear_cancellation
        )
        
        thread_id = "global-test-thread"
        
        try:
            # Use convenience functions
            await request_cancellation(thread_id)
            assert await is_cancelled(thread_id)
            
            await clear_cancellation(thread_id)
            assert not await is_cancelled(thread_id)
        finally:
            # Cleanup
            await clear_cancellation(thread_id)


@pytest.mark.asyncio
async def test_integration_scenario():
    """
    Test a realistic scenario:
    1. Start streaming
    2. User requests cancellation
    3. Stream checks and stops
    4. Flag is cleared
    """
    manager = CancellationManager()
    thread_id = "integration-test"
    
    try:
        # Simulate streaming loop
        chunks_sent = 0
        max_chunks = 100
        
        async def simulate_stream():
            nonlocal chunks_sent
            for i in range(max_chunks):
                # Check for cancellation (would happen in real stream)
                if await manager.is_cancelled(thread_id):
                    break
                
                chunks_sent += 1
                await asyncio.sleep(0.01)  # Simulate work
        
        # Start streaming
        stream_task = asyncio.create_task(simulate_stream())
        
        # Let it run a bit
        await asyncio.sleep(0.1)
        
        # Request cancellation (user clicks stop button)
        await manager.request_cancellation(thread_id)
        
        # Wait for stream to notice and stop
        await stream_task
        
        # Should have stopped early
        assert chunks_sent < max_chunks
        assert chunks_sent > 0  # But sent some chunks
        
        # Clear the flag
        await manager.clear_cancellation(thread_id)
        assert not await manager.is_cancelled(thread_id)
        
    finally:
        await manager.clear_cancellation(thread_id)
