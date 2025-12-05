# Experimental Retrieval Evaluation Guide

This guide explains how to use the experimental evaluation system to test and optimize the retrieval component of Opey II.

## Overview

The evaluation system allows you to:
- **Run experiments** with different retrieval parameters (batch size, k-value, retry thresholds)
- **Export results to CSV** for detailed analysis
- **Generate plots** to visualize performance trade-offs
- **Find optimal configurations** for your specific needs

## Quick Start

### 1. Simple End-to-End Evaluation

Test if your retrieval system is working correctly:

```bash
python scripts/run_retrieval_eval.py quick
```

This runs a quick evaluation (30 queries) and shows:
- Hit rate (% of queries that retrieved at least one relevant document)
- Precision and recall metrics
- Latency percentiles (P50, P99)
- Pass/fail assessment against target thresholds

### 2. Compare Configurations

Compare multiple configurations side-by-side:

```bash
python scripts/run_retrieval_eval.py compare
```

This tests small, medium, and large batch sizes and shows which performs best.

### 3. Run Parameter Sweeps

Find the optimal batch size for your use case:

```bash
python src/evals/retrieval/experiment_runner.py --experiment batch_size
```

This tests batch sizes [3, 5, 8, 10, 15] and generates:
- CSV files with detailed results
- Plots showing latency vs batch size, recall vs batch size, and trade-off analysis
- Recommendation for the best batch size

## Available Experiments

### Batch Size Sweep

Tests different batch sizes to find the sweet spot between latency and recall:

```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 3 5 8 10 15 20
```

**Output:**
- `eval_results/batch_size_sweep_aggregate.csv` - Summary metrics for each batch size
- `eval_results/batch_size_sweep_individual.csv` - Individual query results
- `eval_results/batch_size_sweep_analysis.png` - Visualization with 4 plots:
  1. Latency vs Batch Size
  2. Recall/Precision vs Batch Size  
  3. Latency vs Recall Trade-off
  4. Combined Score (finds optimum)

### K-Value Sweep

Tests different top-k cutoffs for precision/recall evaluation:

```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment k_value \
    --k-values 1 3 5 8 10
```

**Output:**
- CSV files and plots showing how metrics change with k

### Retry Threshold Sweep

Tests different retry thresholds to balance accuracy vs performance:

```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment retry_threshold \
    --retry-thresholds 0 1 2 3
```

**Output:**
- CSV files and plots showing retry rate vs precision trade-off

### Full Experiment

Run all experiments at once:

```bash
python src/evals/retrieval/experiment_runner.py --experiment full
```

## Understanding the Metrics

### Relevancy Metrics

- **Hit Rate**: Percentage of queries that retrieved at least one definitely relevant document
  - Target: ≥50%
  - Higher is better

- **Soft Precision**: Fraction of retrieved docs that are relevant (including "possibly relevant")
  - Target: ≥30%
  - Higher is better
  
- **Soft Recall**: Fraction of all relevant docs that were retrieved
  - Target: ≥50%
  - Higher is better

- **MRR (Mean Reciprocal Rank)**: Average of 1/rank of first relevant doc
  - Range: 0-1
  - Higher is better (1.0 = relevant doc always ranked first)

### Performance Metrics

- **Latency P50/P90/P99**: Percentile latencies in milliseconds
  - Targets: P50 ≤2000ms, P99 ≤5000ms
  - Lower is better

- **Retry Rate**: Percentage of queries that needed retries
  - Lower is better (but may impact accuracy)

## CSV Output Format

### Aggregate Metrics CSV

One row per configuration tested:

| Column | Description |
|--------|-------------|
| `count` | Number of queries evaluated |
| `mean_soft_precision` | Average precision (0-1) |
| `mean_soft_recall` | Average recall (0-1) |
| `hit_rate` | Fraction of queries with hits (0-1) |
| `latency_p50` | 50th percentile latency (ms) |
| `latency_p99` | 99th percentile latency (ms) |
| `retry_rate` | Fraction of queries needing retries (0-1) |
| `config_*` | Configuration parameters (e.g., `config_batch_size`) |

### Individual Results CSV

One row per query:

| Column | Description |
|--------|-------------|
| `query_terms` | The query text |
| `strict_precision` | Precision using only "definitely relevant" docs |
| `soft_precision` | Precision including "possibly relevant" docs |
| `strict_recall` | Recall using only "definitely relevant" docs |
| `soft_recall` | Recall including "possibly relevant" docs |
| `mrr` | Reciprocal rank of first relevant doc |
| `latency_ms` | Query latency in milliseconds |
| `retries` | Number of retries needed |

## Plotting Your Own Data

Use the plotting utilities to visualize any CSV data:

```python
from evals.retrieval.plotting import plot_batch_size_analysis

# Plot batch size analysis
plot_batch_size_analysis(
    aggregate_csv_path="eval_results/batch_size_sweep_aggregate.csv",
    output_path="my_analysis.png",
    show=True
)
```

Or create custom plots:

```python
from evals.retrieval.plotting import plot_parameter_comparison

# Compare any parameter vs any metrics
plot_parameter_comparison(
    aggregate_csv_path="eval_results/my_experiment_aggregate.csv",
    x_param="config_batch_size",
    y_metrics=["mean_soft_recall", "latency_mean", "hit_rate"],
    output_path="custom_plot.png"
)
```

## Advanced Usage

### Custom Experiment Script

Create your own experiment by using the evaluation runner directly:

```python
import asyncio
from evals.retrieval.runner import RetrievalEvalRunner, RunConfig
from evals.retrieval.dataset_generator import EvalDataset
from evals.retrieval.export import export_experiment_results

async def my_experiment():
    # Load dataset
    dataset = EvalDataset.load("src/evals/retrieval/eval_dataset.json")
    
    results_list = []
    
    # Test your custom configurations
    for my_param in [10, 20, 30]:
        config = RunConfig(
            batch_size=my_param,
            k=my_param // 2,
        )
        runner = RetrievalEvalRunner(config)
        
        results = await runner.run_dataset(dataset, limit=50)
        aggregate = runner.compute_aggregate(results)
        
        results_list.append((
            {"my_param": my_param},
            results,
            aggregate
        ))
    
    # Export results
    export_experiment_results(
        "my_experiment",
        results_list,
        "my_results"
    )

asyncio.run(my_experiment())
```

### Export Existing Test Results

If you have pytest results from `test_retrieval_*.py`, you can export them too:

```python
from evals.retrieval.export import export_individual_results_to_csv

# In your test:
results = await retrieval_runner.run_dataset(dataset, limit=50)
aggregate = retrieval_runner.compute_aggregate(results)

# Export
export_individual_results_to_csv(
    results,
    "test_results.csv",
    config_params={"batch_size": 8}
)
```

## Tips for Finding Optimal Configuration

1. **Start with batch size sweep** - This has the biggest impact on both latency and recall
2. **Look at the Combined Score plot** - It balances recall (70%) and speed (30%)
3. **Check your use case requirements**:
   - Need fast responses? Prioritize latency, choose smaller batch size
   - Need high accuracy? Prioritize recall, choose larger batch size
   - Balanced? Use the recommended optimum from the plot
4. **Test with realistic query limits** - Use `--limit 100` or more for final validation
5. **Compare before/after changes** - Run evaluations before and after graph modifications

## Troubleshooting

### Dataset not found

If you get "Dataset not found" error:

```bash
python src/evals/retrieval/dataset_generator.py
```

This generates the evaluation dataset from your vector database.

### Import errors

Make sure dev dependencies are installed:

```bash
poetry install
```

Or if you edited `pyproject.toml` manually:

```bash
pip install pandas matplotlib seaborn
```

### Out of memory

If experiments crash with large datasets:
- Use `--limit` to test with fewer queries
- Test batch sizes incrementally instead of all at once

## Example Workflow

Here's a complete workflow for optimizing retrieval:

```bash
# 1. Quick sanity check
python scripts/run_retrieval_eval.py quick

# 2. If it passes, find optimal batch size
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 3 5 8 10 15

# 3. Look at the plot (eval_results/batch_size_sweep_analysis.png)
#    Note the recommended batch size

# 4. Validate the choice with a longer run
python scripts/run_retrieval_eval.py quick -b 10 -n 100

# 5. Update your .env with the optimal batch size
echo "ENDPOINT_RETRIEVER_BATCH_SIZE=10" >> .env

# 6. Test end-to-end
pytest test/agent/retrieval_evals/ -v
```

## Integration with CI/CD

Add a simple check to your CI pipeline:

```yaml
- name: Validate Retrieval Performance
  run: |
    python scripts/run_retrieval_eval.py quick -n 50
```

This ensures changes don't degrade retrieval performance.
