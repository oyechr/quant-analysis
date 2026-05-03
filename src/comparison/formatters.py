"""
Output formatters for multi-ticker comparison results.

Supports ASCII table, Markdown, JSON, and correlation heatmap outputs.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def format_comparison_table(df: pd.DataFrame, title: str = "") -> str:
    """
    Render a DataFrame as a formatted ASCII table.

    Args:
        df: DataFrame to render (metrics as index, tickers as columns).
        title: Optional title to display above the table.

    Returns:
        Formatted ASCII table string.
    """
    if df.empty:
        return "  (no data available)"

    lines = []
    if title:
        lines.append(f"\n{'=' * 70}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * 70}")

    # Calculate column widths
    index_width = max(len(str(idx)) for idx in df.index)
    index_width = max(index_width, 15)

    col_widths = {}
    for col in df.columns:
        col_width = max(
            len(str(col)),
            max(len(_fmt_cell(df.at[idx, col])) for idx in df.index),
        )
        col_widths[col] = max(col_width, 10)

    # Header
    header = f"  {'Metric':<{index_width}}"
    for col in df.columns:
        header += f"  {col:>{col_widths[col]}}"
    lines.append("")
    lines.append(header)
    lines.append("  " + "-" * (index_width + sum(col_widths.values()) + 2 * len(df.columns)))

    # Rows
    for idx in df.index:
        row = f"  {str(idx):<{index_width}}"
        for col in df.columns:
            val = _fmt_cell(df.at[idx, col])
            row += f"  {val:>{col_widths[col]}}"
        lines.append(row)

    lines.append("")
    return "\n".join(lines)


def format_comparison_markdown(df: pd.DataFrame, title: str = "") -> str:
    """
    Render a DataFrame as a Markdown table.

    Args:
        df: DataFrame to render.
        title: Optional title as Markdown heading.

    Returns:
        Markdown table string.
    """
    if df.empty:
        return "*No data available*\n"

    lines = []
    if title:
        lines.append(f"## {title}\n")

    # Header row
    header = "| Metric |"
    separator = "|--------|"
    for col in df.columns:
        header += f" {col} |"
        separator += "--------|"
    lines.append(header)
    lines.append(separator)

    # Data rows
    for idx in df.index:
        row = f"| {idx} |"
        for col in df.columns:
            val = _fmt_cell(df.at[idx, col])
            row += f" {val} |"
        lines.append(row)

    lines.append("")
    return "\n".join(lines)


def format_comparison_json(
    scores_df: Optional[pd.DataFrame] = None,
    valuation_df: Optional[pd.DataFrame] = None,
    correlation_df: Optional[pd.DataFrame] = None,
    metrics_df: Optional[pd.DataFrame] = None,
    portfolio_stats: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Combine comparison data into a JSON string.

    Args:
        scores_df: Side-by-side scores DataFrame.
        valuation_df: Relative valuation DataFrame.
        correlation_df: Correlation matrix DataFrame.
        metrics_df: Key metrics DataFrame.
        portfolio_stats: Portfolio statistics dict.

    Returns:
        JSON string.
    """
    result: Dict[str, Any] = {}

    if scores_df is not None and not scores_df.empty:
        result["scores"] = _df_to_dict(scores_df)
    if valuation_df is not None and not valuation_df.empty:
        result["relative_valuation"] = _df_to_dict(valuation_df)
    if correlation_df is not None and not correlation_df.empty:
        result["correlation_matrix"] = _df_to_dict(correlation_df)
    if metrics_df is not None and not metrics_df.empty:
        result["key_metrics"] = _df_to_dict(metrics_df)
    if portfolio_stats is not None:
        result["portfolio"] = portfolio_stats

    return json.dumps(result, indent=2, default=str)


def format_correlation_heatmap(
    corr_df: pd.DataFrame,
    save_path: Optional[str] = None,
) -> str:
    """
    Render correlation matrix as ASCII table, optionally saving a chart image.

    Args:
        corr_df: Correlation matrix DataFrame.
        save_path: If provided, saves a matplotlib/seaborn heatmap image to this path.

    Returns:
        ASCII representation of the correlation matrix.
    """
    if corr_df.empty:
        return "  (no correlation data available)"

    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("  CORRELATION MATRIX (Daily Returns)")
    lines.append("=" * 70)

    # Column headers
    col_width = 8
    header = f"  {'':>{col_width}}"
    for col in corr_df.columns:
        header += f"  {col:>{col_width}}"
    lines.append("")
    lines.append(header)
    lines.append("  " + "-" * (col_width + (col_width + 2) * len(corr_df.columns)))

    # Rows
    for idx in corr_df.index:
        row = f"  {str(idx):>{col_width}}"
        for col in corr_df.columns:
            val = corr_df.at[idx, col]
            row += f"  {val:>{col_width}.3f}"
        lines.append(row)

    lines.append("")

    # Optionally save chart
    if save_path:
        _save_heatmap_chart(corr_df, save_path)
        lines.append(f"  Chart saved: {save_path}")
        lines.append("")

    return "\n".join(lines)


def _save_heatmap_chart(corr_df: pd.DataFrame, save_path: str):
    """Save a seaborn heatmap chart to disk."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(
            corr_df,
            annot=True,
            fmt=".3f",
            cmap="RdYlGn",
            center=0,
            vmin=-1,
            vmax=1,
            square=True,
            ax=ax,
        )
        ax.set_title("Daily Returns Correlation Matrix")
        plt.tight_layout()

        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(path), dpi=150)
        plt.close(fig)

        logger.info(f"Correlation heatmap saved to {save_path}")
    except ImportError:
        logger.warning("matplotlib/seaborn not available — skipping chart save")
    except Exception as e:
        logger.error(f"Failed to save heatmap chart: {e}")


def _fmt_cell(value: Any) -> str:
    """Format a single cell value for display."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _df_to_dict(df: pd.DataFrame) -> Dict[str, Any]:
    """Convert DataFrame to a JSON-friendly dict."""
    result: Dict[str, Any] = {}
    for col in df.columns:
        result[col] = {}
        for idx in df.index:
            val = df.at[idx, col]
            if isinstance(val, float) and pd.isna(val):
                result[col][str(idx)] = None
            else:
                result[col][str(idx)] = val
    return result
