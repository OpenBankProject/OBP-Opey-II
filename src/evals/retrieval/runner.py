"""
Evaluation runner for retrieval graph.

Executes queries from an eval dataset against the endpoint retrieval graph
and collects results for metric computation.
"""

import os
import sys
import asyncio
from typing import Optional, Callable
from dataclasses import dataclass

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from evals.retrieval.metrics import RetrievalResult, RetrievalMetrics, AggregateMetrics, Timer
from evals.retrieval.dataset_generator import EvalDataset, EvalQuery


@dataclass
class RunConfig:
    """Configuration for an evaluation run."""
    batch_size: int = 8  # ENDPOINT_RETRIEVER_BATCH_SIZE
    max_retries: int = 2  # ENDPOINT_RETRIEVER_MAX_RETRIES
    retry_threshold: int = 1  # ENDPOINT_RETRIEVER_RETRY_THRESHOLD
    k: Optional[int] = None  # Limit for Precision@K / Recall@K (None = use all retrieved)


class RetrievalEvalRunner:
    """Runs evaluation queries against the endpoint retrieval graph."""
    
    def __init__(self, config: Optional[RunConfig] = None):
        self.config = config or RunConfig()
        self._graph = None
    
    def _get_graph(self):
        """Lazy load the retrieval graph."""
        if self._graph is None:
            from agent.components.retrieval.endpoint_retrieval.endpoint_retrieval_graph import (
                endpoint_retrieval_graph
            )
            self._graph = endpoint_retrieval_graph
        return self._graph
    
    async def run_single_query(self, query: EvalQuery) -> RetrievalResult:
        """Run a single query and return the result."""
        graph = self._get_graph()
        
        with Timer() as timer:
            result = await graph.ainvoke({"question": query.query_terms})
        
        # Extract retrieved endpoint IDs from output
        output_docs = result.get("output_documents", [])
        retrieved_ids = [doc["operation_id"] for doc in output_docs]
        
        # Get retry count from state (if available)
        retries = result.get("total_retries", 0)
        
        return RetrievalResult(
            query_terms=query.query_terms,
            retrieved_ids=retrieved_ids,
            latency_ms=timer.elapsed_ms,
            retries=retries,
            definitely_relevant=query.definitely_relevant,
            possibly_relevant=query.possibly_relevant,
        )
    
    async def run_dataset(
        self, 
        dataset: EvalDataset,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
    ) -> list[tuple[EvalQuery, RetrievalResult, RetrievalMetrics]]:
        """
        Run all queries in dataset and compute metrics.
        
        Returns list of (query, result, metrics) tuples.
        """
        queries = dataset.queries[:limit] if limit else dataset.queries
        results = []
        
        for i, query in enumerate(queries):
            result = await self.run_single_query(query)
            metrics = RetrievalMetrics.compute(result, k=self.config.k)
            results.append((query, result, metrics))
            
            if progress_callback:
                progress_callback(i + 1, len(queries), metrics)
        
        return results
    
    def compute_aggregate(
        self, 
        results: list[tuple[EvalQuery, RetrievalResult, RetrievalMetrics]]
    ) -> AggregateMetrics:
        """Compute aggregate metrics from results."""
        metrics_list = [m for _, _, m in results]
        return AggregateMetrics.compute(metrics_list)


async def run_evaluation(
    dataset_path: str,
    config: Optional[RunConfig] = None,
    limit: Optional[int] = None,
    verbose: bool = True,
) -> tuple[list[tuple[EvalQuery, RetrievalResult, RetrievalMetrics]], AggregateMetrics]:
    """
    Convenience function to run a full evaluation.
    
    Args:
        dataset_path: Path to eval dataset JSON
        config: Run configuration
        limit: Max number of queries to run (for testing)
        verbose: Print progress
        
    Returns:
        Tuple of (individual results, aggregate metrics)
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    # Load dataset
    dataset = EvalDataset.load(dataset_path)
    if verbose:
        print(f"Loaded dataset with {len(dataset.queries)} queries")
    
    # Create runner
    runner = RetrievalEvalRunner(config)
    
    # Progress callback
    def progress(current: int, total: int, metrics: RetrievalMetrics):
        if verbose:
            hit = "✓" if metrics.strict_hit else "✗"
            print(f"  [{current}/{total}] {hit} P={metrics.strict_precision:.2f} latency={metrics.latency_ms:.0f}ms")
    
    # Run evaluation
    if verbose:
        print(f"\nRunning evaluation (k={config.k if config else 'all'})...")
    
    results = await runner.run_dataset(dataset, limit=limit, progress_callback=progress if verbose else None)
    
    # Compute aggregate
    aggregate = runner.compute_aggregate(results)
    
    if verbose:
        aggregate.print_summary()
    
    return results, aggregate


# CLI
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run retrieval evaluation")
    parser.add_argument(
        "-d", "--dataset",
        default="src/evals/retrieval/eval_dataset.json",
        help="Path to eval dataset"
    )
    parser.add_argument(
        "-k", "--top-k",
        type=int,
        default=None,
        help="Evaluate Precision@K, Recall@K (default: all retrieved)"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Limit number of queries (for testing)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Retriever batch size"
    )
    
    args = parser.parse_args()
    
    config = RunConfig(
        batch_size=args.batch_size,
        k=args.top_k,
    )
    
    asyncio.run(run_evaluation(
        dataset_path=args.dataset,
        config=config,
        limit=args.limit,
        verbose=True,
    ))
