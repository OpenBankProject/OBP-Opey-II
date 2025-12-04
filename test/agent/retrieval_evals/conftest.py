"""
Pytest fixtures for retrieval evaluation.

LangSmith Integration:
    When LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY is set, tests 
    marked with @pytest.mark.langsmith will log to LangSmith using:
        from langsmith import testing as t
        t.log_inputs({...})
        t.log_outputs({...})
        t.log_feedback(key="...", score=...)
"""

import os
import sys
from pathlib import Path

# Add src to path FIRST - before any other imports
_this_dir = Path(__file__).parent
_src_dir = _this_dir.parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

import pytest
from dotenv import load_dotenv
load_dotenv()


# Register the langsmith marker to avoid warnings when plugin not active
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "langsmith: mark test for LangSmith logging (requires langsmith pytest plugin)"
    )


# Check if LangSmith is available
LANGSMITH_AVAILABLE = bool(os.getenv("LANGCHAIN_API_KEY"))


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


@pytest.fixture
def langsmith_available():
    """Returns True if LangSmith is configured and available."""
    return LANGSMITH_AVAILABLE
