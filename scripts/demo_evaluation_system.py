#!/usr/bin/env python3
"""
Demo script for the experimental evaluation system.

This demonstrates all the features without requiring the full retrieval graph.
"""

import os
import sys
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
src_dir = script_dir.parent / "src"
sys.path.insert(0, str(src_dir))


def demo_csv_export():
    """Demonstrate CSV export functionality."""
    print("\n" + "=" * 60)
    print("DEMO: CSV Export")
    print("=" * 60)
    
    from evals.retrieval.metrics import RetrievalResult, RetrievalMetrics, AggregateMetrics
    from evals.retrieval.export import export_individual_results_to_csv, export_aggregate_metrics_to_csv
    from dataclasses import dataclass, field
    
    # Mock query
    @dataclass
    class MockQuery:
        query_terms: str
        source_endpoint_id: str
        definitely_relevant: list = field(default_factory=list)
        possibly_relevant: list = field(default_factory=list)
    
    # Create sample results
    results_data = []
    for i in range(5):
        query = MockQuery(
            query_terms=f'sample query {i}',
            source_endpoint_id=f'endpoint_{i}',
            definitely_relevant=[f'endpoint_{i}'],
            possibly_relevant=[f'endpoint_{i+1}']
        )
        
        result = RetrievalResult(
            query_terms=f'sample query {i}',
            retrieved_ids=[f'endpoint_{i}', f'endpoint_{i+1}', f'endpoint_{i+2}'],
            latency_ms=100.0 + i * 20,
            retries=i % 2,
            definitely_relevant=[f'endpoint_{i}'],
            possibly_relevant=[f'endpoint_{i+1}']
        )
        
        metrics = RetrievalMetrics.compute(result)
        results_data.append((query, result, metrics))
    
    # Export individual results
    export_individual_results_to_csv(
        results_data,
        '/tmp/demo_individual.csv',
        {'batch_size': 8, 'experiment': 'demo'}
    )
    print("✓ Individual results exported to: /tmp/demo_individual.csv")
    
    # Show sample
    with open('/tmp/demo_individual.csv', 'r') as f:
        lines = f.readlines()
        print(f"  {len(lines)} rows (including header)")
        print(f"  Header: {lines[0].strip()[:80]}...")
    
    # Export aggregate
    metrics_list = [m for _, _, m in results_data]
    aggregate = AggregateMetrics.compute(metrics_list)
    
    export_aggregate_metrics_to_csv(
        aggregate,
        '/tmp/demo_aggregate.csv',
        {'batch_size': 8, 'experiment': 'demo'},
        append=False
    )
    print("\n✓ Aggregate metrics exported to: /tmp/demo_aggregate.csv")
    print(f"  Hit Rate: {aggregate.hit_rate:.2%}")
    print(f"  Mean Precision: {aggregate.mean_soft_precision:.2%}")
    print(f"  Mean Latency: {aggregate.latency_mean:.0f}ms")


def demo_plotting():
    """Demonstrate plotting functionality."""
    print("\n" + "=" * 60)
    print("DEMO: Plotting")
    print("=" * 60)
    
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️  Plotting requires pandas and matplotlib")
        print("   Install with: pip install pandas matplotlib seaborn")
        return
    
    from evals.retrieval.plotting import plot_batch_size_analysis
    import csv
    
    # Create synthetic data
    test_data = []
    for batch_size in [3, 5, 8, 10, 15]:
        # Simulate performance trade-offs
        latency_base = 500 + batch_size * 80
        recall = 0.35 + (batch_size / 25.0)
        precision = 0.45 + (batch_size / 35.0)
        
        test_data.append({
            'count': 30,
            'mean_strict_precision': precision * 0.85,
            'mean_strict_recall': recall * 0.85,
            'mean_soft_precision': precision,
            'mean_soft_recall': recall,
            'mean_mrr': 0.55,
            'hit_rate': 0.65 + (batch_size / 50.0),
            'latency_p50': latency_base,
            'latency_p90': latency_base * 1.6,
            'latency_p99': latency_base * 2.2,
            'latency_mean': latency_base * 1.1,
            'retry_rate': 0.08,
            'mean_retries': 0.15,
            'config_batch_size': batch_size
        })
    
    # Write CSV
    csv_path = '/tmp/demo_batch_analysis.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=test_data[0].keys())
        writer.writeheader()
        writer.writerows(test_data)
    
    print(f"✓ Created test data: {csv_path}")
    
    # Generate plot
    plot_path = '/tmp/demo_batch_analysis.png'
    plot_batch_size_analysis(
        csv_path,
        output_path=plot_path,
        show=False
    )
    
    print(f"\n✓ Plot generated: {plot_path}")
    print(f"  Size: {os.path.getsize(plot_path)} bytes")
    print("\nThe plot shows:")
    print("  - Latency vs Batch Size")
    print("  - Recall/Precision vs Batch Size")
    print("  - Latency vs Recall Trade-off")
    print("  - Combined Score (identifies optimum)")


def demo_experiment_workflow():
    """Demonstrate the full experiment workflow."""
    print("\n" + "=" * 60)
    print("DEMO: Experiment Workflow")
    print("=" * 60)
    
    print("\nTypical workflow for finding optimal batch size:")
    print()
    print("1. Run quick evaluation to verify system works:")
    print("   $ python scripts/run_retrieval_eval.py quick")
    print()
    print("2. Run batch size sweep experiment:")
    print("   $ python src/evals/retrieval/experiment_runner.py --experiment batch_size")
    print()
    print("3. Review generated files:")
    print("   - src/evals/retrieval/results/batch_size_sweep_aggregate.csv")
    print("   - src/evals/retrieval/results/batch_size_sweep_individual.csv")
    print("   - src/evals/retrieval/results/batch_size_sweep_analysis.png")
    print()
    print("4. The plot will show the recommended batch size")
    print("   based on combined score (70% recall + 30% speed)")
    print()
    print("5. Update .env with optimal value:")
    print("   ENDPOINT_RETRIEVER_BATCH_SIZE=<optimal_value>")
    print()
    print("6. Validate with full evaluation:")
    print("   $ pytest test/agent/retrieval_evals/ -v")


def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("EXPERIMENTAL EVALUATION SYSTEM DEMO")
    print("=" * 60)
    print()
    print("This demo shows the key features of the evaluation system:")
    print("  1. CSV export for analysis")
    print("  2. Plotting for visualization")
    print("  3. Typical experiment workflow")
    
    demo_csv_export()
    demo_plotting()
    demo_experiment_workflow()
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  - Review documentation: docs/EXPERIMENTAL_EVALUATION.md")
    print("  - Try quick eval: python scripts/run_retrieval_eval.py quick")
    print("  - Run experiments: python src/evals/retrieval/experiment_runner.py --help")
    print()


if __name__ == "__main__":
    main()
