#!/usr/bin/env python3
"""
Simple end-to-end retrieval evaluation script.

Quick way to test if changes to the retrieval graph improve performance.
Runs evaluation and shows key metrics immediately.
"""

import os
import sys
import asyncio
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
src_dir = script_dir.parent / "src"
sys.path.insert(0, str(src_dir))

from dotenv import load_dotenv
load_dotenv()

from evals.retrieval.runner import RetrievalEvalRunner, RunConfig, run_evaluation


def print_banner(text: str):
    """Print a banner with text."""
    print("\n" + "=" * 60)
    print(text.center(60))
    print("=" * 60)


async def quick_eval(
    dataset_path: str = "src/evals/retrieval/eval_dataset.json",
    query_limit: int = 30,
    batch_size: int = 8,
):
    """
    Run a quick evaluation with default settings.
    
    Args:
        dataset_path: Path to eval dataset
        query_limit: Number of queries to run (30 is good for quick tests)
        batch_size: Retrieval batch size
    """
    print_banner("QUICK RETRIEVAL EVALUATION")
    
    config = RunConfig(batch_size=batch_size)
    
    print(f"\nConfiguration:")
    print(f"  Dataset: {dataset_path}")
    print(f"  Query limit: {query_limit}")
    print(f"  Batch size: {batch_size}")
    
    try:
        results, aggregate = await run_evaluation(
            dataset_path=dataset_path,
            config=config,
            limit=query_limit,
            verbose=True
        )
        
        # Quick pass/fail assessment
        print_banner("QUICK ASSESSMENT")
        
        passed = []
        failed = []
        
        # Check hit rate
        if aggregate.hit_rate >= 0.5:
            passed.append(f"✓ Hit Rate: {aggregate.hit_rate:.2%} (target: ≥50%)")
        else:
            failed.append(f"✗ Hit Rate: {aggregate.hit_rate:.2%} (target: ≥50%)")
        
        # Check precision
        if aggregate.mean_soft_precision >= 0.3:
            passed.append(f"✓ Precision: {aggregate.mean_soft_precision:.2%} (target: ≥30%)")
        else:
            failed.append(f"✗ Precision: {aggregate.mean_soft_precision:.2%} (target: ≥30%)")
        
        # Check latency
        if aggregate.latency_p50 <= 2000:
            passed.append(f"✓ P50 Latency: {aggregate.latency_p50:.0f}ms (target: ≤2000ms)")
        else:
            failed.append(f"✗ P50 Latency: {aggregate.latency_p50:.0f}ms (target: ≤2000ms)")
        
        if aggregate.latency_p99 <= 5000:
            passed.append(f"✓ P99 Latency: {aggregate.latency_p99:.0f}ms (target: ≤5000ms)")
        else:
            failed.append(f"✗ P99 Latency: {aggregate.latency_p99:.0f}ms (target: ≤5000ms)")
        
        # Print results
        if passed:
            print("\nPassed Checks:")
            for item in passed:
                print(f"  {item}")
        
        if failed:
            print("\nFailed Checks:")
            for item in failed:
                print(f"  {item}")
        
        # Overall status
        if not failed:
            print("\n🎉 All checks passed! Retrieval system is performing well.")
        else:
            print(f"\n⚠️  {len(failed)} check(s) failed. Consider tuning parameters.")
        
        return aggregate
        
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print("\nTo generate the dataset, run:")
        print("  python src/evals/retrieval/dataset_generator.py")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error running evaluation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def compare_configs(
    dataset_path: str = "src/evals/retrieval/eval_dataset.json",
    query_limit: int = 20,
):
    """
    Compare multiple configurations side-by-side.
    
    Args:
        dataset_path: Path to eval dataset
        query_limit: Number of queries to run per config
    """
    from evals.retrieval.dataset_generator import EvalDataset
    
    print_banner("CONFIGURATION COMPARISON")
    
    configs = [
        ("Small Batch", RunConfig(batch_size=3)),
        ("Medium Batch", RunConfig(batch_size=8)),
        ("Large Batch", RunConfig(batch_size=15)),
    ]
    
    print(f"\nTesting {len(configs)} configurations with {query_limit} queries each...")
    
    # Load dataset once
    dataset = EvalDataset.load(dataset_path)
    
    results_data = []
    
    for name, config in configs:
        print(f"\n[{name}] batch_size={config.batch_size}")
        
        runner = RetrievalEvalRunner(config)
        results = await runner.run_dataset(dataset, limit=query_limit)
        aggregate = runner.compute_aggregate(results)
        
        results_data.append((name, config, aggregate))
        
        print(f"  Recall: {aggregate.mean_soft_recall:.2%} | "
              f"Precision: {aggregate.mean_soft_precision:.2%} | "
              f"Latency: {aggregate.latency_mean:.0f}ms")
    
    # Print comparison table
    print("\n" + "=" * 80)
    print("COMPARISON TABLE")
    print("=" * 80)
    print(f"{'Config':<20} {'Recall':>10} {'Precision':>10} {'Hit Rate':>10} {'Latency':>12}")
    print("-" * 80)
    
    for name, config, agg in results_data:
        print(f"{name:<20} {agg.mean_soft_recall:>9.1%} {agg.mean_soft_precision:>9.1%} "
              f"{agg.hit_rate:>9.1%} {agg.latency_mean:>10.0f}ms")
    
    print("=" * 80)
    
    # Find best by combined score
    best_idx = 0
    best_score = 0
    
    for i, (name, config, agg) in enumerate(results_data):
        # Combined score: 70% recall, 30% inverse normalized latency
        max_lat = max(r[2].latency_mean for r in results_data)
        min_lat = min(r[2].latency_mean for r in results_data)
        norm_lat = 1 - ((agg.latency_mean - min_lat) / (max_lat - min_lat + 1))
        
        score = 0.7 * agg.mean_soft_recall + 0.3 * norm_lat
        
        if score > best_score:
            best_score = score
            best_idx = i
    
    best_name = results_data[best_idx][0]
    print(f"\n🏆 Best configuration: {best_name} (score: {best_score:.3f})")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Quick retrieval evaluation tool"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Quick eval command
    quick_parser = subparsers.add_parser("quick", help="Run quick evaluation")
    quick_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=30,
        help="Number of queries to test (default: 30)"
    )
    quick_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=8,
        help="Batch size (default: 8)"
    )
    
    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare configurations")
    compare_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=20,
        help="Number of queries per config (default: 20)"
    )
    
    args = parser.parse_args()
    
    # Default to quick if no command specified
    if not args.command:
        args.command = "quick"
        args.limit = 30
        args.batch_size = 8
    
    # Run command
    if args.command == "quick":
        asyncio.run(quick_eval(
            query_limit=args.limit,
            batch_size=args.batch_size
        ))
    elif args.command == "compare":
        asyncio.run(compare_configs(
            query_limit=args.limit
        ))
