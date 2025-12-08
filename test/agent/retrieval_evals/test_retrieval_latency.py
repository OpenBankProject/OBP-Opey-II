"""
Retrieval latency and performance evaluation tests.

Tests timing and throughput at different batch sizes and configurations.
Use these to optimize retrieval performance.

Run without LangSmith:
    pytest test/agent/retrieval_evals/test_retrieval_latency.py -v
    
With LangSmith:
    LANGCHAIN_API_KEY=... LANGSMITH_TEST_SUITE="retrieval-latency" \
        pytest test/agent/retrieval_evals/test_retrieval_latency.py -v
"""

import os
import pytest
import time

from evals.retrieval.runner import RetrievalEvalRunner, RunConfig


def _try_langsmith_log(func_name: str, *args, **kwargs):
    """Attempt LangSmith logging, silently fail if not in LangSmith context."""
    try:
        from langsmith import testing as t
        func = getattr(t, func_name, None)
        if func:
            func(*args, **kwargs)
    except Exception:
        pass


class TestRetrievalLatency:
    """Test suite for retrieval latency benchmarks."""
    
    MAX_P50_LATENCY_MS = 2000
    MAX_P99_LATENCY_MS = 5000
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    async def test_latency_benchmark(self, get_dataset, retrieval_runner):
        """Benchmark overall retrieval latency."""
        dataset = get_dataset()
        results = await retrieval_runner.run_dataset(
            dataset,
            limit=int(os.getenv("EVAL_QUERY_LIMIT", "30"))
        )
        aggregate = retrieval_runner.compute_aggregate(results)
        
        _try_langsmith_log("log_inputs", {"batch_size": retrieval_runner.config.batch_size})
        # Normalize latencies to 0-1 scores (lower is better, so invert)
        _try_langsmith_log("log_feedback", key="latency_p50_score", 
                         score=1.0 - min(aggregate.latency_p50 / self.MAX_P50_LATENCY_MS, 1.0))
        _try_langsmith_log("log_feedback", key="latency_p90_score", 
                         score=1.0 - min(aggregate.latency_p90 / 4000, 1.0))
        _try_langsmith_log("log_feedback", key="latency_p99_score", 
                         score=1.0 - min(aggregate.latency_p99 / self.MAX_P99_LATENCY_MS, 1.0))
        _try_langsmith_log("log_feedback", key="retry_rate", score=1.0 - aggregate.retry_rate)
        
        print(f"\n--- Latency Benchmark ---")
        print(f"  Batch size: {retrieval_runner.config.batch_size}")
        print(f"  P50: {aggregate.latency_p50:.0f}ms")
        print(f"  P90: {aggregate.latency_p90:.0f}ms")
        print(f"  P99: {aggregate.latency_p99:.0f}ms")
        print(f"  Mean: {aggregate.latency_mean:.0f}ms")
        print(f"  Retry rate: {aggregate.retry_rate:.2%}")
        
        assert aggregate.latency_p50 <= self.MAX_P50_LATENCY_MS, \
            f"P50 latency {aggregate.latency_p50:.0f}ms exceeds threshold {self.MAX_P50_LATENCY_MS}ms"
        assert aggregate.latency_p99 <= self.MAX_P99_LATENCY_MS, \
            f"P99 latency {aggregate.latency_p99:.0f}ms exceeds threshold {self.MAX_P99_LATENCY_MS}ms"


class TestBatchSizeExperiment:
    """
    Experiment with different batch sizes to find optimal configuration.
    Larger batches may improve recall but increase latency.
    """
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    @pytest.mark.parametrize("batch_size", [3, 5, 8, 10, 15])
    async def test_batch_size_comparison(self, get_dataset, batch_size):
        """Compare retrieval performance at different batch sizes."""
        dataset = get_dataset()
        config = RunConfig(batch_size=batch_size)
        runner = RetrievalEvalRunner(config)
        
        sample_size = int(os.getenv("EVAL_QUERY_LIMIT", "20"))
        results = await runner.run_dataset(dataset, limit=sample_size)
        aggregate = runner.compute_aggregate(results)
        
        _try_langsmith_log("log_inputs", {"batch_size": batch_size})
        _try_langsmith_log("log_feedback", key="precision", score=aggregate.mean_soft_precision)
        _try_langsmith_log("log_feedback", key="recall", score=aggregate.mean_soft_recall)
        _try_langsmith_log("log_feedback", key="hit_rate", score=aggregate.hit_rate)
        _try_langsmith_log("log_feedback", key="latency_score", 
                         score=1.0 - min(aggregate.latency_mean / 3000, 1.0))
        _try_langsmith_log("log_feedback", key="retry_rate", score=1.0 - aggregate.retry_rate)
        
        print(f"\n--- Batch Size {batch_size} ---")
        print(f"  Latency (mean): {aggregate.latency_mean:.0f}ms")
        print(f"  Precision:      {aggregate.mean_soft_precision:.2%}")
        print(f"  Recall:         {aggregate.mean_soft_recall:.2%}")
        print(f"  Hit rate:       {aggregate.hit_rate:.2%}")
        print(f"  Retry rate:     {aggregate.retry_rate:.2%}")


class TestRetryThresholdExperiment:
    """
    Experiment with different retry thresholds.
    Lower thresholds mean more retries but potentially better results.
    """
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    @pytest.mark.parametrize("retry_threshold", [0, 1, 2, 3])
    async def test_retry_threshold_comparison(self, get_dataset, retry_threshold):
        """Compare performance at different retry thresholds."""
        dataset = get_dataset()
        config = RunConfig(
            batch_size=8,
            retry_threshold=retry_threshold,
            max_retries=2,
        )
        runner = RetrievalEvalRunner(config)
        
        sample_size = int(os.getenv("EVAL_QUERY_LIMIT", "20"))
        results = await runner.run_dataset(dataset, limit=sample_size)
        aggregate = runner.compute_aggregate(results)
        
        _try_langsmith_log("log_inputs", {"retry_threshold": retry_threshold})
        _try_langsmith_log("log_feedback", key="precision", score=aggregate.mean_soft_precision)
        _try_langsmith_log("log_feedback", key="hit_rate", score=aggregate.hit_rate)
        _try_langsmith_log("log_feedback", key="retry_rate", score=1.0 - aggregate.retry_rate)
        combined = (aggregate.mean_soft_precision * 0.7) + ((1 - aggregate.retry_rate) * 0.3)
        _try_langsmith_log("log_feedback", key="combined_score", score=combined)
        
        print(f"\n--- Retry Threshold {retry_threshold} ---")
        print(f"  Latency (mean): {aggregate.latency_mean:.0f}ms")
        print(f"  Precision:      {aggregate.mean_soft_precision:.2%}")
        print(f"  Hit rate:       {aggregate.hit_rate:.2%}")
        print(f"  Retry rate:     {aggregate.retry_rate:.2%}")
        print(f"  Mean retries:   {aggregate.mean_retries:.2f}")


class TestThroughput:
    """Test overall throughput of the retrieval system."""
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    async def test_queries_per_second(self, get_dataset, retrieval_runner):
        """Measure queries per second throughput."""
        dataset = get_dataset()
        sample_size = int(os.getenv("EVAL_QUERY_LIMIT", "20"))
        
        start = time.perf_counter()
        results = await retrieval_runner.run_dataset(dataset, limit=sample_size)
        elapsed = time.perf_counter() - start
        
        queries_per_second = sample_size / elapsed
        
        _try_langsmith_log("log_inputs", {"query_count": sample_size})
        _try_langsmith_log("log_feedback", key="throughput_score", 
                         score=min(queries_per_second / 2.0, 1.0))
        
        print(f"\n--- Throughput ---")
        print(f"  Queries: {sample_size}")
        print(f"  Total time: {elapsed:.2f}s")
        print(f"  Queries/second: {queries_per_second:.2f}")
        
        min_qps = 0.5
        if queries_per_second < min_qps:
            print(f"  ⚠️  Below target of {min_qps} QPS")
