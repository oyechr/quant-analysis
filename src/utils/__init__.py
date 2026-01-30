"""Utility modules for financial calculations, serialization, and reporting"""

from .dataframe_utils import normalize_datetime_index, safe_get_dataframe_value
from .financial import (
    TRADING_DAYS_PER_YEAR,
    annualize_return,
    annualize_volatility,
    calculate_cagr,
    calculate_daily_returns,
    convert_annual_to_daily_rate,
    to_float,
    validate_price_data,
)
from .report import (
    create_markdown_header,
    format_currency,
    format_number,
    format_percent,
    get_currency_symbol,
    interpret_beta,
    interpret_sharpe_ratio,
    log_calculation_error,
    safe_get,
    save_analysis_report,
    validate_dataframe,
)
from .serialization import (
    clean_for_json,
    dataframe_to_json_dict,
    dataframe_to_records,
    format_date,
    series_to_dataframe,
)

__all__ = [
    # DataFrame utilities
    "normalize_datetime_index",
    "safe_get_dataframe_value",
    # Financial utilities
    "TRADING_DAYS_PER_YEAR",
    "annualize_return",
    "annualize_volatility",
    "calculate_cagr",
    "calculate_daily_returns",
    "convert_annual_to_daily_rate",
    "to_float",
    "validate_price_data",
    # Report utilities
    "create_markdown_header",
    "format_currency",
    "format_number",
    "format_percent",
    "get_currency_symbol",
    "interpret_beta",
    "interpret_sharpe_ratio",
    "log_calculation_error",
    "safe_get",
    "save_analysis_report",
    "validate_dataframe",
    # Serialization utilities
    "clean_for_json",
    "dataframe_to_json_dict",
    "dataframe_to_records",
    "format_date",
    "series_to_dataframe",
]
