import sys
import os
from pathlib import Path
import pytest
import logging

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