"""
Example integration test showing how to export CSV from existing tests.

This demonstrates how to capture test results and export them for analysis.
"""

import os
import sys
import pytest
from pathlib import Path

# Add src to path
_this_dir = Path(__file__).parent
_src_dir = _this_dir.parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from dotenv import load_dotenv
load_dotenv()

from evals.retrieval.runner import RetrievalEvalRunner, RunConfig
from evals.retrieval.export import export_aggregate_metrics_to_csv


class TestCSVExportIntegration:
    """
    Example of integrating CSV export with existing evaluation tests.
    
    This shows how to capture results from parametrized tests and export
    them to CSV for further analysis and plotting.
    """
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("batch_size", [3, 5, 8, 10])
    async def test_batch_size_with_csv_export(self, get_dataset, batch_size):
        """
        Test different batch sizes and export results to CSV.
        
        This can be used to generate data for plotting and finding optimal configs.
        """
        dataset = get_dataset()
        config = RunConfig(batch_size=batch_size, k=batch_size)
        runner = RetrievalEvalRunner(config)
        
        # Run evaluation
        sample_size = int(os.getenv("EVAL_QUERY_LIMIT", "20"))
        results = await runner.run_dataset(dataset, limit=sample_size)
        aggregate = runner.compute_aggregate(results)
        
        # Export to CSV (append mode for multiple batch sizes)
        output_dir = os.getenv("EVAL_OUTPUT_DIR", "eval_results")
        os.makedirs(output_dir, exist_ok=True)
        
        csv_path = os.path.join(output_dir, "batch_size_test_results.csv")
        
        # First test creates file, subsequent tests append
        is_first = batch_size == 3
        export_aggregate_metrics_to_csv(
            aggregate,
            csv_path,
            config_params={"batch_size": batch_size, "k": config.k},
            append=not is_first
        )
        
        # Print results for visibility
        print(f"\n--- Batch Size {batch_size} ---")
        print(f"  Latency (mean): {aggregate.latency_mean:.0f}ms")
        print(f"  Precision:      {aggregate.mean_soft_precision:.2%}")
        print(f"  Recall:         {aggregate.mean_soft_recall:.2%}")
        print(f"  Hit rate:       {aggregate.hit_rate:.2%}")
        
        if batch_size == 10:  # Last test
            print(f"\n✓ Results exported to: {csv_path}")
            print("  Use plotting utilities to visualize:")
            print(f"    from evals.retrieval.plotting import plot_batch_size_analysis")
            print(f"    plot_batch_size_analysis('{csv_path}')")


@pytest.fixture(scope="module")
def cleanup_test_files():
    """Cleanup test output files after module completes."""
    yield
    # Cleanup logic could go here if needed
    pass


# Standalone example showing programmatic usage
async def example_batch_size_sweep_with_export():
    """
    Example: Run batch size sweep and export to CSV programmatically.
    
    This can be run outside of pytest for ad-hoc experiments.
    """
    from evals.retrieval.dataset_generator import EvalDataset
    from evals.retrieval.export import export_experiment_results
    
    # Load dataset
    dataset_path = os.getenv("EVAL_DATASET_PATH", "src/evals/retrieval/eval_dataset.json")
    dataset = EvalDataset.load(dataset_path)
    
    # Test configurations
    batch_sizes = [3, 5, 8, 10, 15]
    results_list = []
    
    print("\nRunning batch size sweep...")
    for batch_size in batch_sizes:
        print(f"  Testing batch_size={batch_size}...")
        
        config = RunConfig(batch_size=batch_size, k=batch_size)
        runner = RetrievalEvalRunner(config)
        
        results = await runner.run_dataset(dataset, limit=20)
        aggregate = runner.compute_aggregate(results)
        
        results_list.append((
            {"batch_size": batch_size, "k": batch_size},
            results,
            aggregate
        ))
        
        print(f"    Recall: {aggregate.mean_soft_recall:.2%}, "
              f"Latency: {aggregate.latency_mean:.0f}ms")
    
    # Export all results
    individual_path, aggregate_path = export_experiment_results(
        "example_batch_sweep",
        results_list,
        "eval_results"
    )
    
    print(f"\n✓ Export complete!")
    print(f"  Individual: {individual_path}")
    print(f"  Aggregate:  {aggregate_path}")
    
    # Generate plot
    try:
        from evals.retrieval.plotting import plot_batch_size_analysis
        plot_path = "eval_results/example_batch_sweep_plot.png"
        plot_batch_size_analysis(aggregate_path, output_path=plot_path, show=False)
        print(f"  Plot:       {plot_path}")
    except ImportError:
        print("  (Plotting requires pandas, matplotlib, seaborn)")
    
    return aggregate_path


if __name__ == "__main__":
    import asyncio
    
    print("=" * 60)
    print("CSV Export Integration Example")
    print("=" * 60)
    
    asyncio.run(example_batch_size_sweep_with_export())
