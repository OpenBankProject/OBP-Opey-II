"""
Core retrieval evaluation metrics.

These are pure functions with no external dependencies beyond standard library.
Can be used standalone or with any test framework.
"""

from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class RetrievalResult:
    """Result of a single retrieval query."""
    query_terms: str
    retrieved_ids: list[str]
    latency_ms: float
    retries: int = 0
    
    # Ground truth
    definitely_relevant: list[str] = field(default_factory=list)
    possibly_relevant: list[str] = field(default_factory=list)


@dataclass 
class RetrievalMetrics:
    """Computed metrics for a single retrieval result."""
    
    # Strict metrics - only "definitely_relevant" counts
    strict_precision: float  # retrieved & definitely_relevant / retrieved
    strict_recall: float     # retrieved & definitely_relevant / definitely_relevant
    strict_hit: bool         # did we retrieve ANY definitely_relevant doc?
    
    # Soft metrics - "possibly_relevant" also counts  
    soft_precision: float    # retrieved & (definitely | possibly) / retrieved
    soft_recall: float       # retrieved & (definitely | possibly) / (definitely | possibly)
    
    # Ranking metrics
    mrr: float  # 1 / rank of first definitely_relevant doc (0 if not found)
    
    # Performance
    latency_ms: float
    retries: int
    
    @classmethod
    def compute(cls, result: RetrievalResult) -> "RetrievalMetrics":
        """Compute all metrics from a retrieval result."""
        retrieved = result.retrieved_ids
        retrieved_set = set(retrieved)
        
        definitely_set = set(result.definitely_relevant)
        possibly_set = set(result.possibly_relevant)
        all_relevant = definitely_set | possibly_set
        
        # Strict metrics
        strict_matches = retrieved_set & definitely_set
        strict_precision = len(strict_matches) / len(retrieved) if retrieved else 0.0
        strict_recall = len(strict_matches) / len(definitely_set) if definitely_set else 0.0
        strict_hit = len(strict_matches) > 0
        
        # Soft metrics
        soft_matches = retrieved_set & all_relevant
        soft_precision = len(soft_matches) / len(retrieved) if retrieved else 0.0
        soft_recall = len(soft_matches) / len(all_relevant) if all_relevant else 0.0
        
        # MRR - find rank of first definitely_relevant doc
        mrr = 0.0
        for i, doc_id in enumerate(retrieved):
            if doc_id in definitely_set:
                mrr = 1.0 / (i + 1)
                break
        
        return cls(
            strict_precision=strict_precision,
            strict_recall=strict_recall,
            strict_hit=strict_hit,
            soft_precision=soft_precision,
            soft_recall=soft_recall,
            mrr=mrr,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )


@dataclass
class AggregateMetrics:
    """Aggregated metrics across multiple queries."""
    
    count: int
    
    # Averages
    mean_strict_precision: float
    mean_strict_recall: float
    mean_soft_precision: float
    mean_soft_recall: float
    mean_mrr: float
    hit_rate: float  # % of queries with at least one strict hit
    
    # Latency percentiles
    latency_p50: float
    latency_p90: float
    latency_p99: float
    latency_mean: float
    
    # Retry stats
    retry_rate: float  # % of queries that needed retries
    mean_retries: float
    
    @classmethod
    def compute(cls, metrics_list: list[RetrievalMetrics]) -> "AggregateMetrics":
        """Aggregate metrics from multiple results."""
        if not metrics_list:
            raise ValueError("Cannot aggregate empty metrics list")
        
        n = len(metrics_list)
        
        # Sort latencies for percentiles
        latencies = sorted(m.latency_ms for m in metrics_list)
        
        def percentile(data: list[float], p: float) -> float:
            idx = int(len(data) * p / 100)
            return data[min(idx, len(data) - 1)]
        
        return cls(
            count=n,
            mean_strict_precision=sum(m.strict_precision for m in metrics_list) / n,
            mean_strict_recall=sum(m.strict_recall for m in metrics_list) / n,
            mean_soft_precision=sum(m.soft_precision for m in metrics_list) / n,
            mean_soft_recall=sum(m.soft_recall for m in metrics_list) / n,
            mean_mrr=sum(m.mrr for m in metrics_list) / n,
            hit_rate=sum(1 for m in metrics_list if m.strict_hit) / n,
            latency_p50=percentile(latencies, 50),
            latency_p90=percentile(latencies, 90),
            latency_p99=percentile(latencies, 99),
            latency_mean=sum(latencies) / n,
            retry_rate=sum(1 for m in metrics_list if m.retries > 0) / n,
            mean_retries=sum(m.retries for m in metrics_list) / n,
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "count": self.count,
            "precision": {
                "strict_mean": round(self.mean_strict_precision, 4),
                "soft_mean": round(self.mean_soft_precision, 4),
            },
            "recall": {
                "strict_mean": round(self.mean_strict_recall, 4),
                "soft_mean": round(self.mean_soft_recall, 4),
            },
            "mrr": round(self.mean_mrr, 4),
            "hit_rate": round(self.hit_rate, 4),
            "latency_ms": {
                "p50": round(self.latency_p50, 2),
                "p90": round(self.latency_p90, 2),
                "p99": round(self.latency_p99, 2),
                "mean": round(self.latency_mean, 2),
            },
            "retries": {
                "rate": round(self.retry_rate, 4),
                "mean": round(self.mean_retries, 2),
            },
        }
    
    def print_summary(self):
        """Print a human-readable summary."""
        print("\n" + "=" * 60)
        print("RETRIEVAL EVALUATION RESULTS")
        print("=" * 60)
        print(f"Queries evaluated: {self.count}")
        print()
        print("RELEVANCY METRICS")
        print(f"  Strict Precision:  {self.mean_strict_precision:.2%}")
        print(f"  Strict Recall:     {self.mean_strict_recall:.2%}")
        print(f"  Soft Precision:    {self.mean_soft_precision:.2%}")
        print(f"  Soft Recall:       {self.mean_soft_recall:.2%}")
        print(f"  MRR:               {self.mean_mrr:.4f}")
        print(f"  Hit Rate:          {self.hit_rate:.2%}")
        print()
        print("LATENCY (ms)")
        print(f"  p50:  {self.latency_p50:>8.2f}")
        print(f"  p90:  {self.latency_p90:>8.2f}")
        print(f"  p99:  {self.latency_p99:>8.2f}")
        print(f"  mean: {self.latency_mean:>8.2f}")
        print()
        print("RETRIES")
        print(f"  Retry Rate:  {self.retry_rate:.2%}")
        print(f"  Mean Retries: {self.mean_retries:.2f}")
        print("=" * 60)


class Timer:
    """Simple context manager for timing code blocks."""
    
    def __init__(self):
        self.elapsed_ms: float = 0
    
    def __enter__(self):
        self._start = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
