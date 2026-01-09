import sys
import os
from pathlib import Path
import pytest
import pytest_asyncio
import logging

from unittest.mock import patch, MagicMock

import pytest
from service.service import app
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

# @pytest_asyncio.fixture(scope="session", loop_scope="session")
# def anyio_backend():
#     return "asyncio"

# @pytest_asyncio.fixture(scope="session", loop_scope="session")
# async def client():
#     async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:5000") as client:
#         print("Client is ready")
#         yield client

@pytest.fixture(scope="session")
def get_obp_consent():
    """Fixture to provide OBP consent JWT for testing"""
    # This is a mock JWT token for testing purposes
    # In a real scenario, you would generate or retrieve a real JWT
    return "mock.jwt.token.for.testing"

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
    
    
@pytest.fixture
def mock_chroma_environment():
    """Set up mocks for ChromaDB environment"""
    with patch("os.getenv", return_value="/test/chromadb"), \
         patch("os.access", return_value=True), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("pathlib.Path.resolve", return_value=Path("/test/chromadb")):
        yield


# Removed unused fixtures that depend on missing imports