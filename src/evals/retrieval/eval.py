#!/usr/bin/env python3
"""
Simple retrieval evaluation script.

Measures latency vs accuracy for different retrieval configurations.
All three parameters (batch_size, retry_threshold, max_retries) can now be
passed via RunnableConfig without restarting the process.

Usage:
    # Quick eval with defaults
    python src/evals/retrieval/eval.py
    
    # Test specific config
    python src/evals/retrieval/eval.py --batch-size 10 --max-retries 1
    
    # Compare multiple configs
    python src/evals/retrieval/eval.py --compare
"""

import asyncio
import csv
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from langchain_core.runnables import RunnableConfig


@dataclass
class EvalResult:
    """Simple evaluation result."""
    queries: int
    hit_rate: float  # % of queries that found at least one relevant doc
    latency_mean: float  # ms
    latency_p50: float  # ms
    latency_p90: float  # ms
    retries_mean: float


async def run_eval(
    batch_size: int = 5,
    retry_threshold: int = 2,
    max_retries: int = 2,
    num_queries: int = 30,
    dataset_path: str = "src/evals/retrieval/eval_dataset.json",
    quiet: bool = False,
) -> EvalResult:
    """Run evaluation with specified config."""
    from agent.components.retrieval.endpoint_retrieval.endpoint_retrieval_graph import (
        endpoint_retrieval_graph as graph
    )
    
    # Load dataset
    with open(dataset_path) as f:
        data = json.load(f)
    queries = data["queries"][:num_queries]
    
    config: RunnableConfig = {
        "configurable": {
            "batch_size": batch_size,
            "retry_threshold": retry_threshold,
            "max_retries": max_retries,
        }
    }
    
    latencies = []
    hits = 0
    total_retries = 0
    
    for i, q in enumerate(queries):
        query_terms = q["query_terms"]
        expected = set(q["definitely_relevant"])
        
        start = time.perf_counter()
        result = await graph.ainvoke({"question": query_terms}, config=config)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        latencies.append(elapsed_ms)
        
        retrieved = {doc["operation_id"] for doc in result.get("output_documents", [])}
        if retrieved & expected:
            hits += 1
        
        retries = result.get("total_retries", 0)
        total_retries += retries
        
        if not quiet:
            hit = "✓" if retrieved & expected else "✗"
            print(f"  [{i+1}/{len(queries)}] {hit} {elapsed_ms:.0f}ms retries={retries}")
    
    latencies.sort()
    n = len(latencies)
    
    return EvalResult(
        queries=n,
        hit_rate=hits / n,
        latency_mean=sum(latencies) / n,
        latency_p50=latencies[n // 2],
        latency_p90=latencies[int(n * 0.9)],
        retries_mean=total_retries / n,
    )


def print_result(label: str, r: EvalResult):
    """Print a single result."""
    print(f"\n{label}")
    print(f"  Hit Rate:     {r.hit_rate:>6.1%}")
    print(f"  Latency Mean: {r.latency_mean:>6.0f} ms")
    print(f"  Latency P50:  {r.latency_p50:>6.0f} ms")
    print(f"  Latency P90:  {r.latency_p90:>6.0f} ms")
    print(f"  Retries Mean: {r.retries_mean:>6.2f}")


def export_to_csv(
    results: list[tuple[str, int, int, int, EvalResult]],
    output_path: str = "src/evals/retrieval/results/comparison.csv"
):
    """Export comparison results to CSV.
    
    Args:
        results: List of (label, batch_size, retry_threshold, max_retries, result)
        output_path: Path to save CSV
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'label', 'batch_size', 'retry_threshold', 'max_retries',
            'queries', 'hit_rate', 'latency_mean', 'latency_p50', 
            'latency_p90', 'retries_mean'
        ])
        
        for label, bs, rt, mr, r in results:
            writer.writerow([
                label, bs, rt, mr, r.queries, r.hit_rate, r.latency_mean,
                r.latency_p50, r.latency_p90, r.retries_mean
            ])
    
    print(f"\n✓ Results exported to: {output_path}")


async def sweep_param(
    param_name: str,
    param_values: list[int],
    num_queries: int = 30,
    batch_size: int = 5,
    retry_threshold: int = 2,
    max_retries: int = 2,
    output_csv: str | None = None,
):
    """Sweep a single parameter while keeping others constant.
    
    Args:
        param_name: One of 'batch_size', 'retry_threshold', 'max_retries'
        param_values: List of values to test for this parameter
        num_queries: Number of queries to test per config
        batch_size: Default batch_size (used if not sweeping this param)
        retry_threshold: Default retry_threshold (used if not sweeping this param)
        max_retries: Default max_retries (used if not sweeping this param)
        output_csv: Optional path to export CSV
    """
    valid_params = ['batch_size', 'retry_threshold', 'max_retries']
    if param_name not in valid_params:
        raise ValueError(f"param_name must be one of {valid_params}, got '{param_name}'")
    
    print(f"\nSweeping {param_name}: {param_values}")
    print(f"Fixed: ", end="")
    if param_name != 'batch_size':
        print(f"batch_size={batch_size} ", end="")
    if param_name != 'retry_threshold':
        print(f"retry_threshold={retry_threshold} ", end="")
    if param_name != 'max_retries':
        print(f"max_retries={max_retries}", end="")
    print(f"\nQueries per config: {num_queries}")
    print("=" * 70)
    
    results = []
    for i, val in enumerate(param_values, 1):
        # Set up config with variable parameter
        kwargs = {
            'batch_size': batch_size,
            'retry_threshold': retry_threshold,
            'max_retries': max_retries,
            'num_queries': num_queries,
            'quiet': True,
        }
        kwargs[param_name] = val
        
        label = f"{param_name}={val}"
        print(f"[{i}/{len(param_values)}] {label:<20}...", end=" ", flush=True)
        
        r = await run_eval(**kwargs)
        
        # Store with actual config values used
        results.append((
            label,
            kwargs['batch_size'],
            kwargs['retry_threshold'],
            kwargs['max_retries'],
            r
        ))
        print(f"hit={r.hit_rate:.1%} lat={r.latency_mean:.0f}ms retries={r.retries_mean:.2f}")
    
    # Summary table
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"{'Config':<20} {'Hit':>8} {'Lat(ms)':>10} {'P90(ms)':>10} {'Retries':>10}")
    print("-" * 70)
    for label, bs, rt, mr, r in results:
        print(f"{label:<20} {r.hit_rate:>7.1%} {r.latency_mean:>10.0f} {r.latency_p90:>10.0f} {r.retries_mean:>10.2f}")
    print("=" * 70)
    
    # Export to CSV if requested
    if output_csv:
        export_to_csv(results, output_csv)
    
    return results


async def compare_configs(num_queries: int = 30, output_csv: str | None = None):
    """Compare multiple configurations."""
    configs = [
        # (label, batch_size, retry_threshold, max_retries)
        ("Fast (no retries)", 5, 1, 0),
        ("Balanced", 5, 2, 2),
        ("Thorough", 8, 2, 3),
        ("Large batch", 10, 2, 2),
    ]
    
    print(f"\nComparing {len(configs)} configurations ({num_queries} queries each)")
    print("=" * 60)
    
    results = []
    for label, bs, rt, mr in configs:
        print(f"\nRunning: {label} (batch={bs}, retry_thresh={rt}, max_retries={mr})")
        r = await run_eval(
            batch_size=bs,
            retry_threshold=rt,
            max_retries=mr,
            num_queries=num_queries,
            quiet=True,
        )
        results.append((label, bs, rt, mr, r))
        print(f"  → Hit: {r.hit_rate:.1%}, Latency: {r.latency_mean:.0f}ms")
    
    # Summary table
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Config':<20} {'Hit Rate':>10} {'Latency':>10} {'P90':>10} {'Retries':>10}")
    print("-" * 60)
    for label, bs, rt, mr, r in results:
        print(f"{label:<20} {r.hit_rate:>9.1%} {r.latency_mean:>9.0f}ms {r.latency_p90:>9.0f}ms {r.retries_mean:>10.2f}")
    print("=" * 60)
    
    # Export to CSV if requested
    if output_csv:
        export_to_csv(results, output_csv)


async def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Simple retrieval evaluation")
    parser.add_argument("-n", "--num-queries", type=int, default=30, help="Number of queries")
    parser.add_argument("--batch-size", type=int, default=5, help="Retriever batch size (k)")
    parser.add_argument("--retry-threshold", type=int, default=2, help="Min relevant docs before retry")
    parser.add_argument("--max-retries", type=int, default=2, help="Max retry attempts")
    parser.add_argument("--compare", action="store_true", help="Compare multiple configs")
    parser.add_argument("--sweep", type=str, default=None, 
                        help="Parameter to sweep: 'batch_size', 'retry_threshold', or 'max_retries'")
    parser.add_argument("--sweep-values", type=str, default=None,
                        help="Comma-separated values to test, e.g. '3,5,8,10'")
    parser.add_argument("-q", "--quiet", action="store_true", help="Less output")
    parser.add_argument("--csv", type=str, default=None, help="Export results to CSV")
    
    args = parser.parse_args()
    
    if args.sweep:
        if not args.sweep_values:
            print("Error: --sweep-values required when using --sweep")
            return
        
        values = [int(v.strip()) for v in args.sweep_values.split(',')]
        output_csv = args.csv or f"src/evals/retrieval/results/sweep_{args.sweep}.csv"
        
        await sweep_param(
            param_name=args.sweep,
            param_values=values,
            num_queries=args.num_queries,
            batch_size=args.batch_size,
            retry_threshold=args.retry_threshold,
            max_retries=args.max_retries,
            output_csv=output_csv,
        )
    elif args.compare:
        output_csv = args.csv or "eval_results/comparison.csv"
        await compare_configs(args.num_queries, output_csv=output_csv)
    else:
        print(f"Evaluating: batch_size={args.batch_size}, retry_threshold={args.retry_threshold}, max_retries={args.max_retries}")
        print(f"Queries: {args.num_queries}")
        print("-" * 40)
        
        r = await run_eval(
            batch_size=args.batch_size,
            retry_threshold=args.retry_threshold,
            max_retries=args.max_retries,
            num_queries=args.num_queries,
            quiet=args.quiet,
        )
        print_result("Results", r)


if __name__ == "__main__":
    asyncio.run(main())
