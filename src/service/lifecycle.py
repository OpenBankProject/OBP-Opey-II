import logging
import asyncio
from typing import AsyncGenerator
from fastapi import FastAPI
from contextlib import asynccontextmanager

from .redis_client import get_redis_client
from auth import initialize_admin_client, close_admin_client
from .streaming.orchestrator_repository import orchestrator_repository
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from .checkpointer import checkpointers

logger = logging.getLogger("service.lifecycle")

async def periodic_orchestrator_cleanup(interval_seconds: int = 600):
    """Periodically clean up inactive orchestrators"""
    while True:
        try:
            logger.info("Running scheduled cleanup of orchestrators")
            removed = orchestrator_repository.cleanup_inactive(max_age_seconds=3600)  # 1 hour timeout
            logger.info(f"Orchestrator cleanup completed: removed {removed} inactive orchestrators")
        except Exception as e:
            logger.error(f"Error during orchestrator cleanup: {e}", exc_info=True)
        
        await asyncio.sleep(interval_seconds)


async def periodic_cancellation_cleanup(interval_seconds: int = 300):
    """Periodically clean up stale cancellation flags"""
    from utils.cancellation_manager import cancellation_manager
    
    while True:
        try:
            logger.info("Running scheduled cleanup of cancellation flags")
            removed = await cancellation_manager.cleanup_old_flags(max_age_minutes=10)
            if removed > 0:
                logger.info(f"Cancellation cleanup completed: removed {removed} stale flags")
        except Exception as e:
            logger.error(f"Error during cancellation cleanup: {e}", exc_info=True)
        
        await asyncio.sleep(interval_seconds)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Initialize redis client
    redis_client = await get_redis_client()
    
    # Initialize admin OBP client
    try:
        await initialize_admin_client(verify_entitlements=True)
    except Exception as e:
        logger.error(f'Failed to initialize admin client: {e}')
        # Continue startup even if admin client fails - it may not be required for all operations
        logger.warning('⚠️  Admin client initialization failed - admin operations will be unavailable')

    cleanup_task = asyncio.create_task(periodic_orchestrator_cleanup())
    cancellation_cleanup_task = asyncio.create_task(periodic_cancellation_cleanup())
    
    # Ensures that the checkpointer is created and closed properly, and that only this one is used
    # for the whole app
    async with AsyncSqliteSaver.from_conn_string('checkpoints.db') as sql_checkpointer:
        checkpointers['aiosql'] = sql_checkpointer
        yield

    # Cleanup during shutdown
    await close_admin_client()
    
    # Cancel cleanup tasks during shutdown
    cleanup_task.cancel()
    cancellation_cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("Orchestrator cleanup task cancelled during shutdown")
    try:
        await cancellation_cleanup_task
    except asyncio.CancelledError:
        logger.info("Cancellation cleanup task cancelled during shutdown")