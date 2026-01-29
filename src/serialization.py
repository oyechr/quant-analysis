"""
Serialization Utilities
Provides consistent DataFrame/Series to JSON conversion with proper handling of:
- NaN values (→ None/null)
- Datetime/Timestamp indices (→ strings)
- Index preservation (dates, quarters, etc.)
"""

import pandas as pd
from typing import Dict, List, Any, Union, Sequence
from datetime import datetime


def format_date(date_value: Any, format_type: str = 'iso') -> str:
    """
    Format date/timestamp values consistently across the codebase
    
    Args:
        date_value: pd.Timestamp, datetime, or string
        format_type: 'iso' (YYYY-MM-DD) or 'readable' (Jan 29, 2026)
        
    Returns:
        Formatted date string
    """
    # Convert to string first
    date_str = str(date_value)
    
    if format_type == 'iso':
        # Extract YYYY-MM-DD portion only (no time/milliseconds)
        return date_str[:10]
    elif format_type == 'readable':
        # Parse and format as readable
        try:
            if isinstance(date_value, (pd.Timestamp, datetime)):
                dt = date_value
            else:
                dt = pd.to_datetime(date_str)
            return dt.strftime('%b %d, %Y')
        except:
            # Fallback to ISO if parsing fails
            return date_str[:10]
    else:
        return date_str[:10]


def dataframe_to_records(
    df: pd.DataFrame,
    preserve_index: bool = True,
    handle_datetimes: bool = True
) -> List[Dict[str, Any]]:
    """
    Convert DataFrame to list of records (dicts) with proper serialization
    
    Args:
        df: DataFrame to convert
        preserve_index: Whether to include index as a column
        handle_datetimes: Whether to convert datetime columns to strings
        
    Returns:
        List of dictionaries suitable for JSON serialization
    """
    if df.empty:
        return []
    
    # Reset index if needed to preserve it as a column
    if preserve_index and df.index.name or not isinstance(df.index, pd.RangeIndex):
        df_copy = df.reset_index()
    else:
        df_copy = df.copy()
    
    # Convert datetime columns to strings
    if handle_datetimes:
        for col in df_copy.select_dtypes(include=['datetime64']).columns:
            df_copy[col] = df_copy[col].astype(str)
        
        # Also handle object columns that might contain Timestamps
        for col in df_copy.select_dtypes(include=['object']).columns:
            if len(df_copy[col]) > 0 and pd.api.types.is_datetime64_any_dtype(df_copy[col]):
                df_copy[col] = df_copy[col].astype(str)
    
    # Replace NaN with None for valid JSON
    df_clean = df_copy.replace({float('nan'): None})
    
    # Cast to correct type for type checker
    records: List[Dict[str, Any]] = df_clean.to_dict('records')  # type: ignore
    return records


def dataframe_to_json_dict(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Convert DataFrame to nested dict format for JSON serialization
    Handles Timestamp column names and NaN values
    
    Args:
        df: DataFrame to convert
        
    Returns:
        Nested dictionary with string keys
    """
    if df.empty:
        return {}
    
    # Replace NaN with None first
    df_clean = df.replace({float('nan'): None})
    
    # Convert to dict
    df_dict = df_clean.to_dict()
    
    # Convert Timestamp keys to strings and handle None values
    return {
        str(key): {
            str(inner_key): val if val is not None else None
            for inner_key, val in inner_dict.items()
        }
        for key, inner_dict in df_dict.items()
    }


def series_to_dataframe(
    series: pd.Series,
    column_name: str,
    index_name: str = 'Date'
) -> pd.DataFrame:
    """
    Convert Series to DataFrame with proper index preservation
    
    Args:
        series: Series to convert
        column_name: Name for the data column
        index_name: Name for the index column
        
    Returns:
        DataFrame with named index
    """
    if series.empty:
        return pd.DataFrame()
    
    df = series.to_frame(name=column_name)
    df.index.name = index_name
    return df


def clean_for_json(data: Any) -> Any:
    """
    Recursively clean data structure for JSON serialization
    Handles NaN, Timestamps, and nested structures
    
    Args:
        data: Data to clean (dict, list, DataFrame, etc.)
        
    Returns:
        JSON-serializable version of data
    """
    if isinstance(data, pd.DataFrame):
        return dataframe_to_records(data)
    elif isinstance(data, pd.Series):
        return data.replace({float('nan'): None}).to_list()
    elif isinstance(data, dict):
        return {k: clean_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_for_json(item) for item in data]
    elif pd.isna(data):
        return None
    elif isinstance(data, (pd.Timestamp, pd.Timedelta)):
        return str(data)
    else:
        return data
