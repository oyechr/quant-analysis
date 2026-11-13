"""
Type Definitions
Provides TypedDict definitions for structured data returned by DataFetcher methods
Improves IDE autocomplete, type checking, and documentation
"""

from typing import Any, TypedDict

import pandas as pd


class TickerInfo(TypedDict, total=False):
    """Information about a stock ticker"""

    symbol: str
    name: str
    sector: str
    industry: str
    market_cap: float | None
    currency: str
    exchange: str
    website: str
    # Valuation metrics
    pe_ratio: float | None
    forward_pe: float | None
    peg_ratio: float | None
    price_to_book: float | None
    price_to_sales: float | None
    # Profitability
    profit_margin: float | None
    operating_margin: float | None
    roe: float | None
    roa: float | None
    # Financial health
    debt_to_equity: float | None
    current_ratio: float | None
    quick_ratio: float | None
    # Dividends
    dividend_yield: float | None
    payout_ratio: float | None
    # Other
    beta: float | None


class FundamentalsData(TypedDict):
    """Fundamental financial statements"""

    income_stmt_quarterly: pd.DataFrame
    income_stmt_annual: pd.DataFrame
    balance_sheet_quarterly: pd.DataFrame
    balance_sheet_annual: pd.DataFrame
    cash_flow_quarterly: pd.DataFrame
    cash_flow_annual: pd.DataFrame


class EarningsData(TypedDict):
    """Earnings history and dates"""

    earnings_history: pd.DataFrame
    earnings_dates: pd.DataFrame


class HoldersData(TypedDict):
    """Institutional and mutual fund holders"""

    institutional_holders: pd.DataFrame
    mutualfund_holders: pd.DataFrame


class DividendsData(TypedDict):
    """Dividend and stock split history"""

    dividends: pd.DataFrame
    splits: pd.DataFrame
    actions: pd.DataFrame


class AnalystRatingsData(TypedDict):
    """Analyst recommendations and upgrades/downgrades"""

    recommendations: pd.DataFrame
    upgrades_downgrades: pd.DataFrame


class NewsArticle(TypedDict, total=False):
    """News article structure from yfinance"""

    content: dict[str, Any]  # Contains title, provider, clickThroughUrl, etc.


# Type aliases for common return types
NewsData = list[NewsArticle]
PriceData = pd.DataFrame  # OHLCV data with datetime index
