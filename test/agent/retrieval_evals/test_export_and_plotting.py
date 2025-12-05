"""
Tests for CSV export and plotting utilities.

These tests verify that the experimental evaluation system works correctly.
"""

import os
import sys
import pytest
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

# Add src to path
_this_dir = Path(__file__).parent
_src_dir = _this_dir.parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from evals.retrieval.metrics import RetrievalResult, RetrievalMetrics, AggregateMetrics
from evals.retrieval.export import (
    export_individual_results_to_csv,
    export_aggregate_metrics_to_csv,
    export_experiment_results,
)


# Mock EvalQuery for testing
@dataclass
class MockEvalQuery:
    query_terms: str
    source_endpoint_id: str
    definitely_relevant: list = field(default_factory=list)
    possibly_relevant: list = field(default_factory=list)


class TestCSVExport:
    """Test CSV export functionality."""
    
    def test_export_individual_results(self):
        """Test exporting individual query results to CSV."""
        # Create test data
        query = MockEvalQuery(
            query_terms='test query',
            source_endpoint_id='endpoint_1',
            definitely_relevant=['endpoint_1'],
            possibly_relevant=['endpoint_2']
        )
        
        result = RetrievalResult(
            query_terms='test query',
            retrieved_ids=['endpoint_1', 'endpoint_2'],
            latency_ms=100.5,
            retries=0,
            definitely_relevant=['endpoint_1'],
            possibly_relevant=['endpoint_2']
        )
        
        metrics = RetrievalMetrics.compute(result)
        
        # Export to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            output_path = f.name
        
        try:
            export_individual_results_to_csv(
                [(query, result, metrics)],
                output_path,
                {'batch_size': 8}
            )
            
            # Verify file was created and has content
            assert os.path.exists(output_path)
            
            with open(output_path, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2  # Header + 1 data row
                assert 'query_terms' in lines[0]
                assert 'strict_precision' in lines[0]
                assert 'config_batch_size' in lines[0]
                assert 'test query' in lines[1]
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)
    
    def test_export_aggregate_metrics(self):
        """Test exporting aggregate metrics to CSV."""
        # Create test metrics
        result = RetrievalResult(
            query_terms='test',
            retrieved_ids=['doc1', 'doc2'],
            latency_ms=150.0,
            retries=0,
            definitely_relevant=['doc1'],
            possibly_relevant=[]
        )
        
        metrics = RetrievalMetrics.compute(result)
        aggregate = AggregateMetrics.compute([metrics])
        
        # Export to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            output_path = f.name
        
        try:
            export_aggregate_metrics_to_csv(
                aggregate,
                output_path,
                {'batch_size': 8},
                append=False
            )
            
            # Verify file
            assert os.path.exists(output_path)
            
            with open(output_path, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2  # Header + 1 data row
                assert 'mean_soft_precision' in lines[0]
                assert 'latency_p50' in lines[0]
                assert 'config_batch_size' in lines[0]
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)
    
    def test_export_aggregate_append(self):
        """Test appending to aggregate CSV."""
        # Create test metrics
        results = [
            RetrievalResult(
                query_terms=f'test_{i}',
                retrieved_ids=['doc1'],
                latency_ms=100.0 + i * 10,
                retries=0,
                definitely_relevant=['doc1'],
                possibly_relevant=[]
            )
            for i in range(3)
        ]
        
        metrics_list = [RetrievalMetrics.compute(r) for r in results]
        aggregate = AggregateMetrics.compute(metrics_list)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            output_path = f.name
        
        try:
            # Export first time
            export_aggregate_metrics_to_csv(
                aggregate,
                output_path,
                {'batch_size': 5},
                append=False
            )
            
            # Append second time
            export_aggregate_metrics_to_csv(
                aggregate,
                output_path,
                {'batch_size': 10},
                append=True
            )
            
            # Verify both rows are present
            with open(output_path, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 3  # Header + 2 data rows
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)


class TestPlotting:
    """Test plotting functionality."""
    
    def test_plot_generation(self):
        """Test that plot generation works without errors."""
        pytest.importorskip("pandas")
        pytest.importorskip("matplotlib")
        pytest.importorskip("seaborn")
        
        from evals.retrieval.plotting import plot_batch_size_analysis
        
        # Create test data
        import csv
        
        test_data = []
        for batch_size in [3, 5, 8]:
            test_data.append({
                'count': 20,
                'mean_strict_precision': 0.4,
                'mean_strict_recall': 0.5,
                'mean_soft_precision': 0.5,
                'mean_soft_recall': 0.6,
                'mean_mrr': 0.5,
                'hit_rate': 0.7,
                'latency_p50': 500 + batch_size * 100,
                'latency_p90': 800 + batch_size * 150,
                'latency_p99': 1000 + batch_size * 200,
                'latency_mean': 600 + batch_size * 120,
                'retry_rate': 0.1,
                'mean_retries': 0.2,
                'config_batch_size': batch_size
            })
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            csv_path = f.name
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.png') as f:
            plot_path = f.name
        
        try:
            # Write CSV
            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=test_data[0].keys())
                writer.writeheader()
                writer.writerows(test_data)
            
            # Generate plot (don't show)
            plot_batch_size_analysis(
                csv_path,
                output_path=plot_path,
                show=False
            )
            
            # Verify plot was created
            assert os.path.exists(plot_path)
            assert os.path.getsize(plot_path) > 0
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)
            if os.path.exists(plot_path):
                os.unlink(plot_path)


class TestMetrics:
    """Test metric computation."""
    
    def test_retrieval_metrics_computation(self):
        """Test that metrics are computed correctly."""
        result = RetrievalResult(
            query_terms='test',
            retrieved_ids=['doc1', 'doc2', 'doc3'],
            latency_ms=100.0,
            retries=0,
            definitely_relevant=['doc1'],
            possibly_relevant=['doc2']
        )
        
        metrics = RetrievalMetrics.compute(result)
        
        # Check strict metrics
        assert metrics.strict_precision == 1/3  # 1 definitely relevant out of 3 retrieved
        assert metrics.strict_recall == 1.0  # Retrieved all definitely relevant
        assert metrics.strict_hit is True
        
        # Check soft metrics
        assert metrics.soft_precision == 2/3  # 2 relevant out of 3 retrieved
        assert metrics.soft_recall == 1.0  # Retrieved all relevant
        
        # Check MRR (doc1 is first in list)
        assert metrics.mrr == 1.0
    
    def test_aggregate_metrics_computation(self):
        """Test aggregate metrics computation."""
        results = [
            RetrievalResult(
                query_terms=f'test_{i}',
                retrieved_ids=['doc1', 'doc2'],
                latency_ms=100.0 + i * 50,
                retries=i % 2,  # Alternate retries
                definitely_relevant=['doc1'],
                possibly_relevant=[]
            )
            for i in range(10)
        ]
        
        metrics_list = [RetrievalMetrics.compute(r) for r in results]
        aggregate = AggregateMetrics.compute(metrics_list)
        
        assert aggregate.count == 10
        assert 0 <= aggregate.mean_soft_precision <= 1
        assert 0 <= aggregate.hit_rate <= 1
        assert aggregate.latency_p50 > 0
        assert aggregate.retry_rate == 0.5  # Half had retries


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
