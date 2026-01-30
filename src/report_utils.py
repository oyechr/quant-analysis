"""
Report Utilities Module

Shared formatting and utility functions for report generation.
Eliminates duplication across report sections and generators.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ==================== Formatting Utilities ====================


def format_number(value: Any) -> str:
    """
    Format numeric values for markdown display

    Args:
        value: Numeric value to format

    Returns:
        Formatted string with appropriate scale (K, M, B, T)
    """
    if value is None:
        return "N/A"
    try:
        num = float(value)
        if abs(num) >= 1_000_000_000_000:  # Trillion
            return f"${num / 1_000_000_000_000:.2f}T"
        elif abs(num) >= 1_000_000_000:  # Billion
            return f"${num / 1_000_000_000:.2f}B"
        elif abs(num) >= 1_000_000:  # Million
            return f"${num / 1_000_000:.2f}M"
        elif abs(num) >= 1_000:  # Thousand
            return f"${num / 1_000:.2f}K"
        else:
            return f"{num:.2f}"
    except (TypeError, ValueError):
        return "N/A"


def format_percent(value: Any) -> str:
    """
    Format percentage values for markdown display

    Args:
        value: Percentage value (as decimal, e.g., 0.15 for 15%)

    Returns:
        Formatted percentage string
    """
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def safe_get(
    data: Dict[str, Any], key: str, default: Any = "N/A", formatter: Optional[Callable] = None
) -> Any:
    """
    Safely extract value from dictionary with optional formatting

    Args:
        data: Dictionary to extract from
        key: Key to retrieve
        default: Default value if key not found or value is None
        formatter: Optional formatting function to apply

    Returns:
        Formatted value or default
    """
    value = data.get(key)
    if value is None:
        return default
    if formatter:
        return formatter(value)
    return value


# ==================== Markdown Generation ====================


def create_markdown_header(ticker: str, title: str, include_timestamp: bool = True) -> List[str]:
    """
    Create standard markdown header for reports

    Args:
        ticker: Stock ticker symbol
        title: Report title (e.g., "Risk Analysis Report")
        include_timestamp: Whether to include generation timestamp

    Returns:
        List of markdown lines
    """
    md = []
    md.append(f"# {ticker} - {title}")
    md.append("")
    if include_timestamp:
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md.append("")
    return md


def save_analysis_report(
    ticker: str,
    output_dir: Path,
    report_type: str,
    content_generator: Callable[[], List[str]],
    file_extension: str = "md",
) -> None:
    """
    Template method for saving analysis reports (markdown or JSON)

    Args:
        ticker: Stock ticker symbol
        output_dir: Base output directory
        report_type: Type of report (e.g., "technical_analysis", "risk_analysis")
        content_generator: Function that generates report content
        file_extension: File extension ("md" or "json")
    """
    reports_dir = output_dir / ticker / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_file = reports_dir / f"{report_type}.{file_extension}"

    try:
        content = content_generator()

        with open(output_file, "w", encoding="utf-8") as f:
            if file_extension == "md":
                f.write("\n".join(content))
            else:
                import json

                json.dump(content, f, indent=2, default=str)

        logger.info(
            f"{report_type.replace('_', ' ').title()} {file_extension.upper()} saved: {output_file}"
        )
    except Exception as e:
        logger.error(f"Error saving {report_type} report: {e}")


# ==================== Validation Utilities ====================


def validate_dataframe(
    df: Any, required_columns: Optional[List[str]] = None, min_rows: int = 1
) -> bool:
    """
    Validate DataFrame has required structure and data

    Args:
        df: DataFrame to validate (or None)
        required_columns: List of required column names
        min_rows: Minimum number of rows required

    Returns:
        True if valid, False otherwise
    """
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame):
        return False

    if df.empty or len(df) < min_rows:
        return False

    if required_columns:
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            return False

    return True


# ==================== Error Handling ====================


def log_calculation_error(metric_name: str, error: Exception) -> None:
    """
    Standardized error logging for metric calculations

    Args:
        metric_name: Name of the metric being calculated
        error: Exception that occurred
    """
    logger.error(f"Error calculating {metric_name}: {error}")


# ==================== Interpretation Helpers ====================


def interpret_sharpe_ratio(sharpe: float) -> str:
    """
    Provide interpretation of Sharpe ratio value

    Args:
        sharpe: Sharpe ratio value

    Returns:
        Interpretation string
    """
    if sharpe > 3.0:
        return "Excellent risk-adjusted performance"
    elif sharpe > 2.0:
        return "Very good risk-adjusted performance"
    elif sharpe > 1.0:
        return "Good risk-adjusted performance"
    elif sharpe > 0:
        return "Positive but modest risk-adjusted return"
    else:
        return "Underperforming risk-free rate"


def interpret_beta(beta: float) -> str:
    """
    Provide interpretation of Beta value

    Args:
        beta: Beta value

    Returns:
        Interpretation string
    """
    if beta > 1.2:
        return "Significantly more volatile than market"
    elif beta > 1.0:
        return "More volatile than market"
    elif beta > 0.8:
        return "Slightly less volatile than market"
    elif beta > 0:
        return "Less volatile than market"
    else:
        return "Moves inversely to market"
