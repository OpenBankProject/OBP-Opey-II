import sys
import os
from pathlib import Path
import pytest
import pytest_asyncio
import logging

import pytest
from service.service import app
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

@pytest_asyncio.fixture(scope="session", loop_scope="session")
def anyio_backend():
    return "asyncio"

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://localhost:5000") as client:
            print("Client is ready")
            yield client
# Add the parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture(scope="session", autouse=True)
def configure_logging():
    """Configure logging for tests."""
    logging.basicConfig(level=logging.INFO)