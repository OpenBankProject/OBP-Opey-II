"""
Experimental evaluation runner for retrieval system.

Easy-to-use tool for running parameter sweeps and generating CSV reports
and visualizations to find optimal retrieval configurations.
"""

import os
import sys
import asyncio
from typing import Optional, List
from dataclasses import dataclass
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from evals.retrieval.runner import RetrievalEvalRunner, RunConfig
from evals.retrieval.dataset_generator import EvalDataset
from evals.retrieval.export import export_experiment_results
from evals.retrieval.plotting import (
    plot_batch_size_analysis,
    plot_parameter_comparison,
    plot_individual_results_distribution,
)


@dataclass
class ExperimentConfig:
    """Configuration for an evaluation experiment."""
    dataset_path: str = "src/evals/retrieval/eval_dataset.json"
    output_dir: str = "eval_results"
    query_limit: Optional[int] = None  # None = all queries
    
    # Parameters to sweep
    batch_sizes: List[int] = None
    k_values: List[int] = None
    retry_thresholds: List[int] = None
    max_retries: int = 2  # Maximum retries for retry threshold experiments
    
    # Plotting options
    generate_plots: bool = True
    show_plots: bool = False


class ExperimentRunner:
    """Runs experimental evaluations with parameter sweeps."""
    
    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.dataset = None
    
    def _load_dataset(self):
        """Load the evaluation dataset."""
        if self.dataset is None:
            if not os.path.exists(self.config.dataset_path):
                raise FileNotFoundError(
                    f"Dataset not found at {self.config.dataset_path}. "
                    "Run dataset_generator.py first."
                )
            self.dataset = EvalDataset.load(self.config.dataset_path)
            print(f"Loaded dataset with {len(self.dataset.queries)} queries")
        return self.dataset
    
    async def run_batch_size_sweep(
        self,
        batch_sizes: Optional[List[int]] = None,
        experiment_name: str = "batch_size_sweep",
    ) -> tuple[str, str]:
        """
        Run experiment sweeping different batch sizes.
        
        Args:
            batch_sizes: List of batch sizes to test
            experiment_name: Name for output files
            
        Returns:
            Tuple of (individual_csv_path, aggregate_csv_path)
        """
        if batch_sizes is None:
            batch_sizes = self.config.batch_sizes or [3, 5, 8, 10, 15]
        
        dataset = self._load_dataset()
        results_list = []
        
        print(f"\n{'='*60}")
        print(f"Running Batch Size Sweep")
        print(f"{'='*60}")
        print(f"Batch sizes: {batch_sizes}")
        print(f"Queries: {self.config.query_limit or len(dataset.queries)}")
        print()
        
        for i, batch_size in enumerate(batch_sizes, 1):
            print(f"[{i}/{len(batch_sizes)}] Testing batch_size={batch_size}...")
            
            config = RunConfig(
                batch_size=batch_size,
                k=batch_size,  # Match k to batch_size
            )
            runner = RetrievalEvalRunner(config)
            
            results = await runner.run_dataset(
                dataset,
                limit=self.config.query_limit
            )
            aggregate = runner.compute_aggregate(results)
            
            # Print quick summary
            print(f"  Latency: {aggregate.latency_mean:.0f}ms | "
                  f"Recall: {aggregate.mean_soft_recall:.2%} | "
                  f"Hit Rate: {aggregate.hit_rate:.2%}")
            
            results_list.append((
                {"batch_size": batch_size, "k": batch_size},
                results,
                aggregate
            ))
        
        # Export results
        print(f"\nExporting results to {self.config.output_dir}/...")
        individual_path, aggregate_path = export_experiment_results(
            experiment_name,
            results_list,
            self.config.output_dir
        )
        
        print(f"  Individual results: {individual_path}")
        print(f"  Aggregate results: {aggregate_path}")
        
        # Generate plots
        if self.config.generate_plots:
            print("\nGenerating plots...")
            plot_path = os.path.join(
                self.config.output_dir,
                f"{experiment_name}_analysis.png"
            )
            plot_batch_size_analysis(
                aggregate_path,
                output_path=plot_path,
                show=self.config.show_plots
            )
        
        return individual_path, aggregate_path
    
    async def run_k_value_sweep(
        self,
        k_values: Optional[List[int]] = None,
        batch_size: int = 10,
        experiment_name: str = "k_value_sweep",
    ) -> tuple[str, str]:
        """
        Run experiment sweeping different k values (top-k retrieval).
        
        Args:
            k_values: List of k values to test
            batch_size: Fixed batch size to use
            experiment_name: Name for output files
            
        Returns:
            Tuple of (individual_csv_path, aggregate_csv_path)
        """
        if k_values is None:
            k_values = self.config.k_values or [1, 3, 5, 8, 10]
        
        dataset = self._load_dataset()
        results_list = []
        
        print(f"\n{'='*60}")
        print(f"Running K-Value Sweep")
        print(f"{'='*60}")
        print(f"K values: {k_values}")
        print(f"Batch size: {batch_size}")
        print(f"Queries: {self.config.query_limit or len(dataset.queries)}")
        print()
        
        for i, k in enumerate(k_values, 1):
            print(f"[{i}/{len(k_values)}] Testing k={k}...")
            
            config = RunConfig(
                batch_size=batch_size,
                k=k,
            )
            runner = RetrievalEvalRunner(config)
            
            results = await runner.run_dataset(
                dataset,
                limit=self.config.query_limit
            )
            aggregate = runner.compute_aggregate(results)
            
            print(f"  Precision: {aggregate.mean_soft_precision:.2%} | "
                  f"Recall: {aggregate.mean_soft_recall:.2%}")
            
            results_list.append((
                {"batch_size": batch_size, "k": k},
                results,
                aggregate
            ))
        
        # Export results
        print(f"\nExporting results to {self.config.output_dir}/...")
        individual_path, aggregate_path = export_experiment_results(
            experiment_name,
            results_list,
            self.config.output_dir
        )
        
        print(f"  Individual results: {individual_path}")
        print(f"  Aggregate results: {aggregate_path}")
        
        # Generate plots
        if self.config.generate_plots:
            print("\nGenerating plots...")
            plot_path = os.path.join(
                self.config.output_dir,
                f"{experiment_name}_analysis.png"
            )
            plot_parameter_comparison(
                aggregate_path,
                x_param='config_k',
                y_metrics=['mean_soft_precision', 'mean_soft_recall', 'hit_rate'],
                output_path=plot_path,
                show=self.config.show_plots,
                title='K-Value Analysis: Precision, Recall, Hit Rate'
            )
        
        return individual_path, aggregate_path
    
    async def run_retry_threshold_sweep(
        self,
        retry_thresholds: Optional[List[int]] = None,
        batch_size: int = 8,
        experiment_name: str = "retry_threshold_sweep",
    ) -> tuple[str, str]:
        """
        Run experiment sweeping different retry thresholds.
        
        Args:
            retry_thresholds: List of retry thresholds to test
            batch_size: Fixed batch size to use
            experiment_name: Name for output files
            
        Returns:
            Tuple of (individual_csv_path, aggregate_csv_path)
        """
        if retry_thresholds is None:
            retry_thresholds = self.config.retry_thresholds or [0, 1, 2, 3]
        
        dataset = self._load_dataset()
        results_list = []
        
        print(f"\n{'='*60}")
        print(f"Running Retry Threshold Sweep")
        print(f"{'='*60}")
        print(f"Retry thresholds: {retry_thresholds}")
        print(f"Batch size: {batch_size}")
        print(f"Queries: {self.config.query_limit or len(dataset.queries)}")
        print()
        
        for i, threshold in enumerate(retry_thresholds, 1):
            print(f"[{i}/{len(retry_thresholds)}] Testing retry_threshold={threshold}...")
            
            config = RunConfig(
                batch_size=batch_size,
                retry_threshold=threshold,
                max_retries=self.config.max_retries,
            )
            runner = RetrievalEvalRunner(config)
            
            results = await runner.run_dataset(
                dataset,
                limit=self.config.query_limit
            )
            aggregate = runner.compute_aggregate(results)
            
            print(f"  Retry Rate: {aggregate.retry_rate:.2%} | "
                  f"Precision: {aggregate.mean_soft_precision:.2%}")
            
            results_list.append((
                {"batch_size": batch_size, "retry_threshold": threshold},
                results,
                aggregate
            ))
        
        # Export results
        print(f"\nExporting results to {self.config.output_dir}/...")
        individual_path, aggregate_path = export_experiment_results(
            experiment_name,
            results_list,
            self.config.output_dir
        )
        
        print(f"  Individual results: {individual_path}")
        print(f"  Aggregate results: {aggregate_path}")
        
        # Generate plots
        if self.config.generate_plots:
            print("\nGenerating plots...")
            plot_path = os.path.join(
                self.config.output_dir,
                f"{experiment_name}_analysis.png"
            )
            plot_parameter_comparison(
                aggregate_path,
                x_param='config_retry_threshold',
                y_metrics=['mean_soft_precision', 'retry_rate', 'latency_mean'],
                output_path=plot_path,
                show=self.config.show_plots,
                title='Retry Threshold Analysis'
            )
        
        return individual_path, aggregate_path
    
    async def run_full_experiment(self) -> dict:
        """
        Run a comprehensive experiment with all configured parameter sweeps.
        
        Returns:
            Dictionary with paths to all generated files
        """
        results = {}
        
        # Batch size sweep
        if self.config.batch_sizes:
            ind, agg = await self.run_batch_size_sweep()
            results['batch_size'] = {'individual': ind, 'aggregate': agg}
        
        # K value sweep
        if self.config.k_values:
            ind, agg = await self.run_k_value_sweep()
            results['k_value'] = {'individual': ind, 'aggregate': agg}
        
        # Retry threshold sweep
        if self.config.retry_thresholds:
            ind, agg = await self.run_retry_threshold_sweep()
            results['retry_threshold'] = {'individual': ind, 'aggregate': agg}
        
        print(f"\n{'='*60}")
        print("Experiment Complete!")
        print(f"{'='*60}")
        print(f"Results saved to: {self.config.output_dir}/")
        
        return results


# CLI
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description="Run experimental evaluations on retrieval system"
    )
    parser.add_argument(
        "-d", "--dataset",
        default="src/evals/retrieval/eval_dataset.json",
        help="Path to eval dataset"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="eval_results",
        help="Output directory for results"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Limit number of queries (for testing)"
    )
    parser.add_argument(
        "--experiment",
        choices=["batch_size", "k_value", "retry_threshold", "full"],
        default="batch_size",
        help="Type of experiment to run"
    )
    parser.add_argument(
        "--batch-sizes",
        type=int,
        nargs="+",
        default=[3, 5, 8, 10, 15],
        help="Batch sizes to test"
    )
    parser.add_argument(
        "--k-values",
        type=int,
        nargs="+",
        default=[1, 3, 5, 8, 10],
        help="K values to test"
    )
    parser.add_argument(
        "--retry-thresholds",
        type=int,
        nargs="+",
        default=[0, 1, 2, 3],
        help="Retry thresholds to test"
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip plot generation"
    )
    parser.add_argument(
        "--show-plots",
        action="store_true",
        help="Display plots interactively"
    )
    
    args = parser.parse_args()
    
    # Create experiment configuration
    exp_config = ExperimentConfig(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        query_limit=args.limit,
        batch_sizes=args.batch_sizes,
        k_values=args.k_values,
        retry_thresholds=args.retry_thresholds,
        generate_plots=not args.no_plots,
        show_plots=args.show_plots,
    )
    
    # Create runner
    runner = ExperimentRunner(exp_config)
    
    # Run experiment
    if args.experiment == "batch_size":
        asyncio.run(runner.run_batch_size_sweep())
    elif args.experiment == "k_value":
        asyncio.run(runner.run_k_value_sweep())
    elif args.experiment == "retry_threshold":
        asyncio.run(runner.run_retry_threshold_sweep())
    elif args.experiment == "full":
        asyncio.run(runner.run_full_experiment())
