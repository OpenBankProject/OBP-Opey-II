import sys
import os
from pathlib import Path
import pytest
import logging

# Add the parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture(scope="session", autouse=True)
def configure_logging():
    """Configure logging for tests."""
    logging.basicConfig(level=logging.INFO)