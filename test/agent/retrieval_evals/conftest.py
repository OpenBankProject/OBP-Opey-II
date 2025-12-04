"""
Pytest fixtures for retrieval evaluation.

LangSmith Integration:
    When running with --langsmith-output, tests marked with @pytest.mark.langsmith
    will log feedback scores. Use get_dataset() to avoid logging the full dataset.
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


# Module-level cache for dataset (not a fixture, so not logged)
_cached_dataset = None


def _load_dataset():
    """Load dataset without exposing it as a fixture parameter."""
    global _cached_dataset
    if _cached_dataset is None:
        from evals.retrieval.dataset_generator import EvalDataset
        dataset_path = os.getenv(
            "EVAL_DATASET_PATH",
            "src/evals/retrieval/eval_dataset.json"
        )
        if not os.path.exists(dataset_path):
            pytest.skip(f"Dataset not found at {dataset_path}. Run dataset_generator.py first.")
        _cached_dataset = EvalDataset.load(dataset_path)
    return _cached_dataset


@pytest.fixture(scope="session")
def get_dataset():
    """Returns a callable that loads the dataset (avoids LangSmith logging the full dataset)."""
    return _load_dataset


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
def sample_queries(get_dataset):
    """Get a small sample of queries for quick tests."""
    import random
    dataset = get_dataset()
    sample_size = int(os.getenv("EVAL_SAMPLE_SIZE", "10"))
    return random.sample(dataset.queries, min(sample_size, len(dataset.queries)))
