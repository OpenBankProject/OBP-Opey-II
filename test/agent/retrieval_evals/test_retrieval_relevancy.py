"""
Retrieval relevancy evaluation tests.

Tests precision, recall, and ranking metrics for the endpoint retrieval graph.
When LangSmith is configured, tests marked with @pytest.mark.langsmith will
log inputs, outputs, and feedback scores.

Run without LangSmith:
    pytest test/agent/retrieval_evals/test_retrieval_relevancy.py -v
    
With LangSmith:
    LANGCHAIN_API_KEY=... LANGSMITH_TEST_SUITE="retrieval-relevancy" \
        pytest test/agent/retrieval_evals/test_retrieval_relevancy.py -v
"""

import os
import pytest
from evals.retrieval.metrics import RetrievalMetrics, AggregateMetrics


def _try_langsmith_log(func_name: str, *args, **kwargs):
    """Attempt LangSmith logging, silently fail if not in LangSmith context."""
    try:
        from langsmith import testing as t
        func = getattr(t, func_name, None)
        if func:
            func(*args, **kwargs)
    except Exception:
        pass  # Not in LangSmith context or not configured


class TestRetrievalRelevancy:
    """Test suite for retrieval relevancy metrics."""
    
    # Minimum acceptable thresholds
    MIN_HIT_RATE = 0.5
    MIN_SOFT_PRECISION = 0.3
    MIN_MRR = 0.3
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    async def test_aggregate_relevancy(self, eval_dataset, retrieval_runner):
        """
        Test overall retrieval relevancy across the dataset.
        Runs all queries and computes aggregate metrics.
        """
        results = await retrieval_runner.run_dataset(
            eval_dataset, 
            limit=int(os.getenv("EVAL_QUERY_LIMIT", "50"))
        )
        aggregate = retrieval_runner.compute_aggregate(results)
        
        # LangSmith logging
        _try_langsmith_log("log_inputs", {
            "dataset_size": len(eval_dataset.queries),
            "queries_evaluated": aggregate.count,
        })
        _try_langsmith_log("log_outputs", aggregate.to_dict())
        _try_langsmith_log("log_feedback", key="hit_rate", score=aggregate.hit_rate)
        _try_langsmith_log("log_feedback", key="soft_precision", score=aggregate.mean_soft_precision)
        _try_langsmith_log("log_feedback", key="soft_recall", score=aggregate.mean_soft_recall)
        _try_langsmith_log("log_feedback", key="mrr", score=aggregate.mean_mrr)
        
        aggregate.print_summary()
        
        assert aggregate.hit_rate >= self.MIN_HIT_RATE, \
            f"Hit rate {aggregate.hit_rate:.2%} below threshold {self.MIN_HIT_RATE:.2%}"
        assert aggregate.mean_soft_precision >= self.MIN_SOFT_PRECISION, \
            f"Soft precision {aggregate.mean_soft_precision:.2%} below threshold {self.MIN_SOFT_PRECISION:.2%}"
        assert aggregate.mean_mrr >= self.MIN_MRR, \
            f"MRR {aggregate.mean_mrr:.4f} below threshold {self.MIN_MRR}"
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    @pytest.mark.parametrize("k", [1, 3, 5, 8])
    async def test_precision_at_k(self, eval_dataset, retrieval_runner, k):
        """Test Precision@K at different cutoffs."""
        retrieval_runner.config.k = k
        
        results = await retrieval_runner.run_dataset(
            eval_dataset,
            limit=int(os.getenv("EVAL_QUERY_LIMIT", "30"))
        )
        aggregate = retrieval_runner.compute_aggregate(results)
        
        _try_langsmith_log("log_inputs", {"k": k})
        _try_langsmith_log("log_outputs", {
            f"precision@{k}": aggregate.mean_strict_precision,
            f"soft_precision@{k}": aggregate.mean_soft_precision,
            f"recall@{k}": aggregate.mean_strict_recall,
        })
        _try_langsmith_log("log_feedback", key=f"precision_at_{k}", score=aggregate.mean_strict_precision)
        
        print(f"\n--- Precision@{k} ---")
        print(f"  Strict: {aggregate.mean_strict_precision:.2%}")
        print(f"  Soft:   {aggregate.mean_soft_precision:.2%}")
        print(f"  Recall: {aggregate.mean_strict_recall:.2%}")
        
        retrieval_runner.config.k = None
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    async def test_individual_query_samples(self, sample_queries, retrieval_runner):
        """Run individual query samples to debug specific failure cases."""
        failures = []
        
        for query in sample_queries:
            result = await retrieval_runner.run_single_query(query)
            metrics = RetrievalMetrics.compute(result)
            
            _try_langsmith_log("log_inputs", {
                "query_terms": query.query_terms,
                "expected_endpoint": query.source_endpoint_id,
            })
            _try_langsmith_log("log_outputs", {
                "retrieved": result.retrieved_ids[:5],
                "hit": metrics.strict_hit,
                "precision": metrics.strict_precision,
            })
            
            if not metrics.strict_hit:
                failures.append({
                    "query": query.query_terms,
                    "expected": query.source_endpoint_id,
                    "got": result.retrieved_ids[:3],
                })
        
        if failures:
            print(f"\n--- Failed queries ({len(failures)}/{len(sample_queries)}) ---")
            for f in failures[:5]:
                print(f"  Query: {f['query'][:50]}...")
                print(f"    Expected: {f['expected']}")
                print(f"    Got: {f['got']}")
        
        failure_rate = len(failures) / len(sample_queries)
        print(f"\nFailure rate: {failure_rate:.2%}")


class TestRetrievalByTag:
    """Test retrieval performance broken down by tag."""
    
    @pytest.mark.asyncio
    @pytest.mark.langsmith
    async def test_performance_by_tag(self, eval_dataset, retrieval_runner):
        """
        Analyze retrieval performance by endpoint tag.
        Identifies which endpoint categories are harder to retrieve.
        """
        from collections import defaultdict
        
        tag_results = defaultdict(list)
        endpoint_map = {ep.operation_id: ep for ep in eval_dataset.endpoints}
        
        results = await retrieval_runner.run_dataset(
            eval_dataset,
            limit=int(os.getenv("EVAL_QUERY_LIMIT", "50"))
        )
        
        for query, result, metrics in results:
            endpoint = endpoint_map.get(query.source_endpoint_id)
            if endpoint:
                for tag in endpoint.tags:
                    tag_results[tag].append(metrics)
        
        print("\n--- Performance by Tag ---")
        tag_metrics = {}
        
        for tag, metrics_list in sorted(tag_results.items(), key=lambda x: -len(x[1])):
            if len(metrics_list) < 3:
                continue
            
            agg = AggregateMetrics.compute(metrics_list)
            tag_metrics[tag] = {
                "count": agg.count,
                "hit_rate": agg.hit_rate,
                "precision": agg.mean_soft_precision,
            }
            print(f"  {tag:40} n={agg.count:3} hit={agg.hit_rate:.0%} prec={agg.mean_soft_precision:.0%}")
        
        _try_langsmith_log("log_outputs", {"tag_metrics": tag_metrics})
        
        # Log worst performing tags
        worst_tags = sorted(tag_metrics.items(), key=lambda x: x[1]["hit_rate"])[:3]
        for tag, metrics in worst_tags:
            _try_langsmith_log("log_feedback", key=f"worst_tag_{tag[:20]}_hit_rate", score=metrics["hit_rate"])
