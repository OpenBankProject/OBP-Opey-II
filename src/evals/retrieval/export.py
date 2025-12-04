"""
CSV export utilities for retrieval evaluation results.

Exports individual query results and aggregate metrics to CSV format
for analysis and visualization.
"""

import csv
from typing import Optional, TYPE_CHECKING
from pathlib import Path
from dataclasses import asdict

from evals.retrieval.metrics import RetrievalResult, RetrievalMetrics, AggregateMetrics

if TYPE_CHECKING:
    from evals.retrieval.dataset_generator import EvalQuery

# Maximum length for query terms in CSV (to keep files readable)
MAX_QUERY_LENGTH = 100


def export_individual_results_to_csv(
    results: list[tuple["EvalQuery", RetrievalResult, RetrievalMetrics]],
    output_path: str,
    config_params: Optional[dict] = None,
) -> None:
    """
    Export individual query results to CSV.
    
    Args:
        results: List of (query, result, metrics) tuples
        output_path: Path to output CSV file
        config_params: Optional configuration parameters to include (e.g., batch_size, k)
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        header = [
            'query_terms',
            'strict_precision',
            'strict_recall',
            'strict_hit',
            'soft_precision',
            'soft_recall',
            'mrr',
            'latency_ms',
            'retries',
            'retrieved_count',
            'definitely_relevant_count',
            'possibly_relevant_count',
        ]
        
        # Add config params to header if provided
        if config_params:
            for key in sorted(config_params.keys()):
                header.append(f'config_{key}')
        
        writer.writerow(header)
        
        # Data rows
        for query, result, metrics in results:
            row = [
                query.query_terms[:MAX_QUERY_LENGTH],  # Truncate long queries
                metrics.strict_precision,
                metrics.strict_recall,
                1 if metrics.strict_hit else 0,
                metrics.soft_precision,
                metrics.soft_recall,
                metrics.mrr,
                metrics.latency_ms,
                metrics.retries,
                len(result.retrieved_ids),
                len(result.definitely_relevant),
                len(result.possibly_relevant),
            ]
            
            # Add config values
            if config_params:
                for key in sorted(config_params.keys()):
                    row.append(config_params[key])
            
            writer.writerow(row)


def export_aggregate_metrics_to_csv(
    aggregate: AggregateMetrics,
    output_path: str,
    config_params: Optional[dict] = None,
    append: bool = True,
) -> None:
    """
    Export aggregate metrics to CSV.
    
    Args:
        aggregate: Aggregate metrics object
        output_path: Path to output CSV file
        config_params: Optional configuration parameters to include
        append: If True and file exists, append row. If False, overwrite.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Check if file exists and has content
    file_exists = Path(output_path).exists() and Path(output_path).stat().st_size > 0
    
    mode = 'a' if (append and file_exists) else 'w'
    
    with open(output_path, mode, newline='') as f:
        # Build header and row
        header = [
            'count',
            'mean_strict_precision',
            'mean_strict_recall',
            'mean_soft_precision',
            'mean_soft_recall',
            'mean_mrr',
            'hit_rate',
            'latency_p50',
            'latency_p90',
            'latency_p99',
            'latency_mean',
            'retry_rate',
            'mean_retries',
        ]
        
        row = [
            aggregate.count,
            aggregate.mean_strict_precision,
            aggregate.mean_strict_recall,
            aggregate.mean_soft_precision,
            aggregate.mean_soft_recall,
            aggregate.mean_mrr,
            aggregate.hit_rate,
            aggregate.latency_p50,
            aggregate.latency_p90,
            aggregate.latency_p99,
            aggregate.latency_mean,
            aggregate.retry_rate,
            aggregate.mean_retries,
        ]
        
        # Add config params
        if config_params:
            for key in sorted(config_params.keys()):
                header.append(f'config_{key}')
                row.append(config_params[key])
        
        writer = csv.writer(f)
        
        # Write header only if creating new file
        if mode == 'w':
            writer.writerow(header)
        
        writer.writerow(row)


def export_experiment_results(
    experiment_name: str,
    results_list: list[tuple[dict, list, AggregateMetrics]],
    output_dir: str = "eval_results",
) -> tuple[str, str]:
    """
    Export results from multiple experiment configurations.
    
    Args:
        experiment_name: Name of the experiment (used in filenames)
        results_list: List of (config_params, individual_results, aggregate) tuples
        output_dir: Directory to save results
        
    Returns:
        Tuple of (individual_csv_path, aggregate_csv_path)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    individual_path = output_path / f"{experiment_name}_individual.csv"
    aggregate_path = output_path / f"{experiment_name}_aggregate.csv"
    
    # Export all individual results to one file
    all_individual = []
    for config_params, results, _ in results_list:
        for query, result, metrics in results:
            all_individual.append((query, result, metrics))
    
    if all_individual:
        # Get config from first result
        first_config = results_list[0][0]
        export_individual_results_to_csv(
            all_individual,
            str(individual_path),
            first_config
        )
    
    # Export aggregate results (one row per config)
    for i, (config_params, _, aggregate) in enumerate(results_list):
        export_aggregate_metrics_to_csv(
            aggregate,
            str(aggregate_path),
            config_params,
            append=(i > 0)
        )
    
    return str(individual_path), str(aggregate_path)
