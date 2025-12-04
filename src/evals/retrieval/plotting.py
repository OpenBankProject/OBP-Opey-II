"""
Plotting utilities for retrieval evaluation results.

Creates visualizations to help find optimal retrieval configurations.
"""

import csv
from pathlib import Path
from typing import Optional


def plot_batch_size_analysis(
    aggregate_csv_path: str,
    output_path: Optional[str] = None,
    show: bool = True,
) -> None:
    """
    Create plots showing batch size vs latency and recall/precision.
    
    Args:
        aggregate_csv_path: Path to aggregate metrics CSV
        output_path: Optional path to save plot image
        show: Whether to display the plot interactively
    """
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        print("Error: pandas, matplotlib, and seaborn are required for plotting.")
        print("Install with: poetry add --group dev pandas matplotlib seaborn")
        return
    
    # Set style
    sns.set_theme(style="whitegrid")
    
    # Load data
    df = pd.read_csv(aggregate_csv_path)
    
    # Check if batch_size column exists
    if 'config_batch_size' not in df.columns:
        print("Warning: 'config_batch_size' column not found in CSV.")
        print(f"Available columns: {list(df.columns)}")
        return
    
    # Sort by batch size
    df = df.sort_values('config_batch_size')
    
    # Create figure with subplots
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Batch Size Analysis', fontsize=16, fontweight='bold')
    
    # Plot 1: Batch Size vs Latency
    ax1 = axes[0, 0]
    ax1.plot(df['config_batch_size'], df['latency_mean'], 
             marker='o', linewidth=2, markersize=8, label='Mean')
    ax1.plot(df['config_batch_size'], df['latency_p50'], 
             marker='s', linewidth=2, markersize=6, label='P50', alpha=0.7)
    ax1.plot(df['config_batch_size'], df['latency_p90'], 
             marker='^', linewidth=2, markersize=6, label='P90', alpha=0.7)
    ax1.set_xlabel('Batch Size', fontsize=12)
    ax1.set_ylabel('Latency (ms)', fontsize=12)
    ax1.set_title('Latency vs Batch Size', fontsize=13, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Batch Size vs Recall/Precision
    ax2 = axes[0, 1]
    ax2.plot(df['config_batch_size'], df['mean_soft_recall'], 
             marker='o', linewidth=2, markersize=8, label='Soft Recall', color='#2ecc71')
    ax2.plot(df['config_batch_size'], df['mean_soft_precision'], 
             marker='s', linewidth=2, markersize=8, label='Soft Precision', color='#3498db')
    ax2.plot(df['config_batch_size'], df['hit_rate'], 
             marker='^', linewidth=2, markersize=8, label='Hit Rate', color='#e74c3c')
    ax2.set_xlabel('Batch Size', fontsize=12)
    ax2.set_ylabel('Score', fontsize=12)
    ax2.set_title('Recall/Precision vs Batch Size', fontsize=13, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim([0, 1.05])
    
    # Plot 3: Trade-off (Latency vs Recall)
    ax3 = axes[1, 0]
    scatter = ax3.scatter(df['latency_mean'], df['mean_soft_recall'], 
                         s=df['config_batch_size']*20, 
                         c=df['config_batch_size'], 
                         cmap='viridis', 
                         alpha=0.6, 
                         edgecolors='black',
                         linewidth=1.5)
    
    # Annotate points with batch size
    for _, row in df.iterrows():
        ax3.annotate(f"{int(row['config_batch_size'])}", 
                    (row['latency_mean'], row['mean_soft_recall']),
                    fontsize=9, ha='center', va='center')
    
    ax3.set_xlabel('Mean Latency (ms)', fontsize=12)
    ax3.set_ylabel('Soft Recall', fontsize=12)
    ax3.set_title('Latency vs Recall Trade-off', fontsize=13, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax3)
    cbar.set_label('Batch Size', fontsize=10)
    
    # Plot 4: Combined Score
    ax4 = axes[1, 1]
    # Calculate a combined score: weighted average of recall and inverse latency
    # Normalize latency to 0-1 (lower is better)
    max_latency = df['latency_mean'].max()
    min_latency = df['latency_mean'].min()
    normalized_latency = 1 - ((df['latency_mean'] - min_latency) / (max_latency - min_latency))
    
    # Combined score: 70% recall, 30% speed
    combined_score = 0.7 * df['mean_soft_recall'] + 0.3 * normalized_latency
    
    ax4.plot(df['config_batch_size'], combined_score, 
             marker='o', linewidth=2.5, markersize=10, color='#9b59b6', label='Combined Score')
    
    # Mark the best configuration
    best_idx = combined_score.idxmax()
    best_batch_size = df.loc[best_idx, 'config_batch_size']
    best_score = combined_score.loc[best_idx]
    
    ax4.axvline(x=best_batch_size, color='red', linestyle='--', alpha=0.5, label=f'Best: {int(best_batch_size)}')
    ax4.plot(best_batch_size, best_score, 'r*', markersize=20, label='Optimum')
    
    ax4.set_xlabel('Batch Size', fontsize=12)
    ax4.set_ylabel('Combined Score', fontsize=12)
    ax4.set_title('Combined Score (70% Recall + 30% Speed)', fontsize=13, fontweight='bold')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim([0, 1.05])
    
    plt.tight_layout()
    
    # Save if output path provided
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    
    # Show if requested
    if show:
        plt.show()
    
    plt.close()
    
    # Print summary
    print("\n" + "=" * 60)
    print("BATCH SIZE ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Best batch size: {int(best_batch_size)}")
    print(f"Combined score: {best_score:.4f}")
    print(f"Recall at best: {df.loc[best_idx, 'mean_soft_recall']:.2%}")
    print(f"Latency at best: {df.loc[best_idx, 'latency_mean']:.0f}ms")
    print("=" * 60)


def plot_parameter_comparison(
    aggregate_csv_path: str,
    x_param: str,
    y_metrics: list[str],
    output_path: Optional[str] = None,
    show: bool = True,
    title: Optional[str] = None,
) -> None:
    """
    Create a flexible plot comparing a parameter against multiple metrics.
    
    Args:
        aggregate_csv_path: Path to aggregate metrics CSV
        x_param: Parameter to plot on x-axis (e.g., 'config_batch_size')
        y_metrics: List of metrics to plot on y-axis
        output_path: Optional path to save plot
        show: Whether to display the plot
        title: Optional plot title
    """
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        print("Error: pandas, matplotlib, and seaborn are required for plotting.")
        return
    
    sns.set_theme(style="whitegrid")
    
    # Load data
    df = pd.read_csv(aggregate_csv_path)
    
    # Verify columns exist
    if x_param not in df.columns:
        print(f"Error: '{x_param}' not found in CSV.")
        print(f"Available columns: {list(df.columns)}")
        return
    
    for metric in y_metrics:
        if metric not in df.columns:
            print(f"Warning: '{metric}' not found in CSV, skipping.")
            y_metrics.remove(metric)
    
    if not y_metrics:
        print("Error: No valid metrics to plot.")
        return
    
    # Sort by x parameter
    df = df.sort_values(x_param)
    
    # Create plot
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for metric in y_metrics:
        ax.plot(df[x_param], df[metric], 
               marker='o', linewidth=2, markersize=8, label=metric)
    
    ax.set_xlabel(x_param.replace('config_', '').replace('_', ' ').title(), fontsize=12)
    ax.set_ylabel('Value', fontsize=12)
    ax.set_title(title or f'{x_param} vs Metrics', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    
    if show:
        plt.show()
    
    plt.close()


def plot_individual_results_distribution(
    individual_csv_path: str,
    output_path: Optional[str] = None,
    show: bool = True,
) -> None:
    """
    Create distribution plots for individual query results.
    
    Args:
        individual_csv_path: Path to individual results CSV
        output_path: Optional path to save plot
        show: Whether to display the plot
    """
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        print("Error: pandas, matplotlib, and seaborn are required for plotting.")
        return
    
    sns.set_theme(style="whitegrid")
    
    # Load data
    df = pd.read_csv(individual_csv_path)
    
    # Create figure
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Individual Query Results Distribution', fontsize=16, fontweight='bold')
    
    # Plot 1: Latency distribution
    ax1 = axes[0, 0]
    ax1.hist(df['latency_ms'], bins=30, edgecolor='black', alpha=0.7, color='skyblue')
    ax1.axvline(df['latency_ms'].median(), color='red', linestyle='--', 
               linewidth=2, label=f'Median: {df["latency_ms"].median():.0f}ms')
    ax1.set_xlabel('Latency (ms)', fontsize=12)
    ax1.set_ylabel('Frequency', fontsize=12)
    ax1.set_title('Latency Distribution', fontsize=13, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Plot 2: Precision distribution
    ax2 = axes[0, 1]
    ax2.hist(df['soft_precision'], bins=20, edgecolor='black', alpha=0.7, color='lightgreen')
    ax2.axvline(df['soft_precision'].mean(), color='red', linestyle='--', 
               linewidth=2, label=f'Mean: {df["soft_precision"].mean():.2f}')
    ax2.set_xlabel('Soft Precision', fontsize=12)
    ax2.set_ylabel('Frequency', fontsize=12)
    ax2.set_title('Precision Distribution', fontsize=13, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Plot 3: Recall distribution
    ax3 = axes[1, 0]
    ax3.hist(df['soft_recall'], bins=20, edgecolor='black', alpha=0.7, color='lightcoral')
    ax3.axvline(df['soft_recall'].mean(), color='red', linestyle='--', 
               linewidth=2, label=f'Mean: {df["soft_recall"].mean():.2f}')
    ax3.set_xlabel('Soft Recall', fontsize=12)
    ax3.set_ylabel('Frequency', fontsize=12)
    ax3.set_title('Recall Distribution', fontsize=13, fontweight='bold')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')
    
    # Plot 4: Hit rate pie chart
    ax4 = axes[1, 1]
    hit_counts = df['strict_hit'].value_counts()
    colors = ['#2ecc71', '#e74c3c']
    labels = ['Hit', 'Miss']
    ax4.pie(hit_counts, labels=labels, autopct='%1.1f%%', 
           colors=colors, startangle=90, textprops={'fontsize': 12})
    ax4.set_title('Hit Rate', fontsize=13, fontweight='bold')
    
    plt.tight_layout()
    
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    
    if show:
        plt.show()
    
    plt.close()
