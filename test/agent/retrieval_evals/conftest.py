"""
Pytest fixtures for retrieval evaluation.

IMPORTANT: This conftest must be loaded before the test modules to set up paths.
"""

import os
import sys
from pathlib import Path

# Add src to path FIRST - before any other imports
_this_dir = Path(__file__).parent
_src_dir = _this_dir.parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

# Now safe to import
import pytest
import asyncio
from typing import Optional

from dotenv import load_dotenv
load_dotenv()


# Check if LangSmith is configured
LANGSMITH_ENABLED = (
    os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true" 
    and os.getenv("LANGCHAIN_API_KEY")
)


@pytest.fixture(scope="session")
def eval_dataset():
    """Load the evaluation dataset."""
    from evals.retrieval.dataset_generator import EvalDataset
    
    dataset_path = os.getenv(
        "EVAL_DATASET_PATH",
        "src/evals/retrieval/eval_dataset.json"
    )
    
    if not os.path.exists(dataset_path):
        pytest.skip(f"Dataset not found at {dataset_path}. Run dataset_generator.py first.")
    
    return EvalDataset.load(dataset_path)


@pytest.fixture(scope="session")
def retrieval_runner():
    """Create a retrieval evaluation runner."""
    from evals.retrieval.runner import RetrievalEvalRunner, RunConfig
    
    config = RunConfig(
        batch_size=int(os.getenv("ENDPOINT_RETRIEVER_BATCH_SIZE", "8")),
        max_retries=int(os.getenv("ENDPOINT_RETRIEVER_MAX_RETRIES", "2")),
        retry_threshold=int(os.getenv("ENDPOINT_RETRIEVER_RETRY_THRESHOLD", "1")),
    )
    return RetrievalEvalRunner(config)


@pytest.fixture
def sample_queries(eval_dataset):
    """Get a small sample of queries for quick tests."""
    import random
    sample_size = int(os.getenv("EVAL_SAMPLE_SIZE", "10"))
    return random.sample(eval_dataset.queries, min(sample_size, len(eval_dataset.queries)))


def langsmith_mark():
    """
    Return the langsmith marker if enabled, otherwise a no-op marker.
    
    This allows tests to optionally integrate with LangSmith without
    requiring it to be configured.
    """
    if LANGSMITH_ENABLED:
        return pytest.mark.langsmith
    return pytest.mark.skipif(False, reason="")  # No-op marker


# Conditionally import langsmith testing utilities
if LANGSMITH_ENABLED:
    try:
        from langsmith import testing as langsmith_testing
    except ImportError:
        langsmith_testing = None
        LANGSMITH_ENABLED = False
else:
    langsmith_testing = None


@pytest.fixture
def ls():
    """
    LangSmith testing utilities (or None if not configured).
    
    Usage:
        def test_something(ls):
            if ls:
                ls.log_inputs({"query": "..."})
                ls.log_outputs({"result": "..."})
                ls.log_feedback(key="precision", score=0.8)
    """
    return langsmith_testing
