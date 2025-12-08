# Evaluation Quick Start Guide

Fast reference for running retrieval evaluations and experiments.

## Quick Commands

### 1. Test if Retrieval Works (30 seconds)

```bash
python scripts/run_retrieval_eval.py quick
```

**Output:** Pass/fail on hit rate, precision, and latency targets.

### 2. Compare Configurations (1 minute)

```bash
python scripts/run_retrieval_eval.py compare
```

**Output:** Side-by-side comparison of small/medium/large batch sizes.

### 3. Find Optimal Batch Size (2-5 minutes)

```bash
python src/evals/retrieval/experiment_runner.py --experiment batch_size
```

**Output:** 
- CSV files with detailed metrics
- Plot showing latency vs batch size, recall vs batch size, and recommended optimum
- Location: `src/evals/retrieval/results/batch_size_sweep_*`

### 4. Custom Batch Size Test

```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 5 7 9 11 \
    --limit 50
```

### 5. Test Retry Thresholds

```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment retry_threshold \
    --retry-thresholds 0 1 2 3
```

### 6. Run All Experiments

```bash
python src/evals/retrieval/experiment_runner.py --experiment full
```

## Understanding Output

### CSV Files

Two types of files are generated:

1. **`*_aggregate.csv`** - One row per configuration
   - Summary metrics (mean precision, recall, latency percentiles)
   - Use this for plotting and comparison

2. **`*_individual.csv`** - One row per query
   - Detailed per-query metrics
   - Use this for debugging specific failures

### Plots

Batch size analysis creates a 4-panel plot:
1. **Top-left**: Latency (P50/P90/Mean) vs Batch Size
2. **Top-right**: Precision/Recall/Hit Rate vs Batch Size
3. **Bottom-left**: Latency vs Recall trade-off scatter
4. **Bottom-right**: Combined score (70% recall + 30% speed) - shows optimum

## Key Metrics

| Metric | Good Value | Meaning |
|--------|-----------|---------|
| **Hit Rate** | ≥50% | % queries retrieving ≥1 relevant doc |
| **Soft Precision** | ≥30% | % retrieved docs that are relevant |
| **Soft Recall** | ≥50% | % relevant docs that were retrieved |
| **P50 Latency** | ≤2000ms | Median query time |
| **P99 Latency** | ≤5000ms | 99th percentile query time |
| **Retry Rate** | <20% | % queries needing retries |

## Common Scenarios

### Scenario: Changes Made to Retrieval Graph

```bash
# 1. Quick sanity check
python scripts/run_retrieval_eval.py quick -n 30

# 2. If passed, validate with more queries
python scripts/run_retrieval_eval.py quick -n 100

# 3. Export results for comparison
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 8 \
    -n 100 \
    -o src/evals/retrieval/results/after_change
```

### Scenario: System is Too Slow

```bash
# Test smaller batch sizes
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 3 5 8 \
    -n 50

# Look at plot - find batch size with acceptable latency
# Update .env: ENDPOINT_RETRIEVER_BATCH_SIZE=<value>
```

### Scenario: Recall is Too Low

```bash
# Test larger batch sizes and k values
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 8 10 15 20 \
    -n 50

# Look at plot - find batch size with best recall
# Update .env: ENDPOINT_RETRIEVER_BATCH_SIZE=<value>
```

### Scenario: Need Data for a Report

```bash
# Run full evaluation with all queries
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --output-dir report_data

# Generate custom plots
python -c "
from evals.retrieval.plotting import plot_batch_size_analysis
plot_batch_size_analysis(
    'report_data/batch_size_sweep_aggregate.csv',
    output_path='report_plot.png',
    show=False
)
"
```

## Environment Variables

Control behavior with environment variables:

```bash
# Limit queries for faster tests
export EVAL_QUERY_LIMIT=20

# Change output directory
export EVAL_OUTPUT_DIR=my_results

# Use different dataset
export EVAL_DATASET_PATH=path/to/dataset.json
```

## Troubleshooting

### "Dataset not found"

Generate the dataset first:
```bash
python src/evals/retrieval/dataset_generator.py
```

### Import errors (pandas, matplotlib, etc.)

Install dev dependencies:
```bash
pip install pandas matplotlib seaborn
# Or with poetry:
poetry install --with dev
```

### Out of memory

Use smaller query limits:
```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --limit 20
```

### Tests are slow

Reduce query limit or batch size range:
```bash
python src/evals/retrieval/experiment_runner.py \
    --experiment batch_size \
    --batch-sizes 5 8 10 \
    --limit 30
```

## Integration with CI/CD

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Validate Retrieval Performance
  run: |
    python scripts/run_retrieval_eval.py quick -n 50
```

This ensures PRs don't degrade retrieval performance.

## Next Steps

- Full documentation: [EXPERIMENTAL_EVALUATION.md](EXPERIMENTAL_EVALUATION.md)
- Demo script: `python scripts/demo_evaluation_system.py`
- Example integration: `test/agent/retrieval_evals/test_csv_export_integration.py`
