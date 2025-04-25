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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:5000") as client:
        print("Client is ready")
        yield client
# Add the parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set the environment variable for the test suite
# os.environ["OBP_BASE_URL"] = os.getenv("OBP_TEST_URL")
# os.environ["OBP_PASSWORD"] = os.getenv("OBP_TEST_PASSWORD")
# os.environ["OBP_USERNAME"] = os.getenv("OBP_TEST_USERNAME")
# os.environ["OBP_CONSUMER_KEY"] = os.getenv("OBP_TEST_CONSUMER_KEY")

@pytest.fixture(scope="session", autouse=True)
def configure_logging():
    """Configure logging for tests."""
    logging.basicConfig(level=logging.INFO)