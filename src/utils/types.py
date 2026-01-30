"""
Type Definitions
Provides TypedDict definitions for structured data returned by DataFetcher methods
Improves IDE autocomplete, type checking, and documentation
"""

from typing import Any, Dict, List, Optional, TypedDict

import pandas as pd


class TickerInfo(TypedDict, total=False):
    """Information about a stock ticker"""

    symbol: str
    name: str
    sector: str
    industry: str
    market_cap: Optional[float]
    currency: str
    exchange: str
    website: str
    # Valuation metrics
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    peg_ratio: Optional[float]
    price_to_book: Optional[float]
    price_to_sales: Optional[float]
    # Profitability
    profit_margin: Optional[float]
    operating_margin: Optional[float]
    roe: Optional[float]
    roa: Optional[float]
    # Financial health
    debt_to_equity: Optional[float]
    current_ratio: Optional[float]
    quick_ratio: Optional[float]
    # Dividends
    dividend_yield: Optional[float]
    payout_ratio: Optional[float]
    # Other
    beta: Optional[float]


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

    content: Dict[str, Any]  # Contains title, provider, clickThroughUrl, etc.


# Type aliases for common return types
NewsData = List[NewsArticle]
PriceData = pd.DataFrame  # OHLCV data with datetime index
