import sys
import os
from pathlib import Path
import pytest
import pytest_asyncio
import logging

from unittest.mock import patch, MagicMock
from src.agent.components.retrieval.retriever_config import (
    ChromaVectorStoreFactory,
    VectorStoreConfig
)

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


@pytest.fixture
def chroma_factory(mock_chroma_environment):
    """Create a properly configured ChromaVectorStoreFactory"""
    return ChromaVectorStoreFactory()


@pytest.fixture
def valid_config():
    """Create a valid VectorStoreConfig"""
    return VectorStoreConfig(
        collection_name="test_collection",
        embedding_model="text-embedding-3-large",
        search_type="similarity",
        search_kwargs={"k": 5}
    )