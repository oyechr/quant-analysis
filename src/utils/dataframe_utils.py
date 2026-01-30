"""
DataFrame Utilities

Helper functions for working with pandas DataFrames and Series,
particularly for financial data with datetime indices.
"""

from typing import Any, Optional

import pandas as pd


def normalize_datetime_index(series: pd.Series) -> pd.Series:
    """
    Normalize a Series to have a timezone-naive DatetimeIndex

    Ensures consistent datetime index handling across the codebase by:
    1. Converting to DatetimeIndex if not already
    2. Removing timezone information (converting to naive)

    Args:
        series: Series with datetime-like index

    Returns:
        Series with normalized timezone-naive DatetimeIndex
    """
    result = series.copy()

    # Convert to DatetimeIndex if not already
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, utc=True)

    # Remove timezone if present (convert to naive for consistent comparisons)
    if isinstance(result.index, pd.DatetimeIndex) and result.index.tz is not None:
        result.index = result.index.tz_localize(None)

    return result


def safe_get_dataframe_value(
    df: Optional[pd.DataFrame], row_name: str, col_index: int = 0
) -> Optional[float]:
    """
    Safely extract a numeric value from a DataFrame

    Handles common edge cases:
    - None or empty DataFrame
    - Missing row/column
    - NaN values
    - Series returned instead of scalar

    Args:
        df: DataFrame to extract from
        row_name: Name of the row (index value)
        col_index: Column index position (default: 0 for most recent)

    Returns:
        Float value or None if extraction fails
    """
    if df is None or df.empty:
        return None

    try:
        if row_name in df.index:
            value = df.loc[row_name].iloc[col_index]

            # Handle case where .iloc returns a Series
            if isinstance(value, pd.Series):
                value = value.iloc[0]

            # Return float or None for NaN
            return float(value) if pd.notna(value) and value is not None else None

    except (KeyError, IndexError, ValueError, TypeError):
        pass

    return None
