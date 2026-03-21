"""Checkpoint-specific test configuration that doesn't require service imports."""
import sys
from pathlib import Path
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

@pytest.fixture(scope="module")
def anyio_backend():
    """Use asyncio only for these tests."""
    return "asyncio"
