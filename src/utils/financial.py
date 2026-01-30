"""
Financial Calculation Utilities

Provides reusable financial calculations and type-safe conversions
used across technical, fundamental, and risk analysis modules.
"""

from typing import Any

import numpy as np
import pandas as pd

# Financial constants
TRADING_DAYS_PER_YEAR = 252


def to_float(value: Any) -> float:
    """
    Safely convert pandas Scalar/numpy types to Python float

    Args:
        value: Value to convert (Scalar, numpy number, int, float, etc.)

    Returns:
        Python float, or 0.0 if conversion fails
    """
    if isinstance(value, (int, float, np.number)):
        return float(value)
    return 0.0


def calculate_daily_returns(price_data: pd.DataFrame, column: str = "Close") -> pd.Series:
    """
    Calculate daily returns from price data

    Args:
        price_data: DataFrame with price data
        column: Column name to calculate returns from (default: 'Close')

    Returns:
        Series of daily percentage returns (NaN values dropped)
    """
    return price_data[column].pct_change().dropna()


def annualize_return(daily_return: float, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """
    Convert daily return to annualized return

    Args:
        daily_return: Daily return rate
        periods: Number of periods per year (default: 252 trading days)

    Returns:
        Annualized return
    """
    return daily_return * periods


def annualize_volatility(daily_volatility: float, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """
    Convert daily volatility to annualized volatility

    Args:
        daily_volatility: Daily standard deviation
        periods: Number of periods per year (default: 252 trading days)

    Returns:
        Annualized volatility (standard deviation)
    """
    return daily_volatility * np.sqrt(periods)


def validate_price_data(price_data: pd.DataFrame, column: str = "Close") -> bool:
    """
    Validate that price data has required column and contains data

    Args:
        price_data: DataFrame to validate
        column: Required column name (default: 'Close')

    Returns:
        True if valid, False otherwise
    """
    return price_data is not None and not price_data.empty and column in price_data.columns


def convert_annual_to_daily_rate(annual_rate_pct: float) -> float:
    """
    Convert annual rate (percentage) to daily rate

    Args:
        annual_rate_pct: Annual rate as percentage (e.g., 4.0 for 4%)

    Returns:
        Daily rate as decimal
    """
    return (1 + annual_rate_pct / 100) ** (1 / TRADING_DAYS_PER_YEAR) - 1


def calculate_cagr(ending_value: float, beginning_value: float, num_periods: int) -> float:
    """
    Calculate Compound Annual Growth Rate

    Args:
        ending_value: Final value
        beginning_value: Initial value
        num_periods: Number of periods (years)

    Returns:
        CAGR as percentage, or 0.0 if calculation invalid
    """
    if ending_value is None or beginning_value is None or beginning_value <= 0 or num_periods <= 0:
        return 0.0
    return (pow(ending_value / beginning_value, 1 / num_periods) - 1) * 100
