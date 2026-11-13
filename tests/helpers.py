"""
Plain builders shared by the tests: synthetic prices, statements and
yfinance-shaped context, plus small report, scoring and red-flag records.

Fixtures live in conftest.py; anything a test imports lives here, so no test
imports conftest or another test module.
"""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.scoring.dimensions import DimensionResult
from src.scoring.scorer import ScoringResult
from src.vetting.red_flags import RedFlag

_EXCHANGE_TZ = {".OL": "Europe/Oslo", ".L": "Europe/London"}


def _exchange_tz(symbol: str) -> str:
    for suffix, tz in _EXCHANGE_TZ.items():
        if symbol.upper().endswith(suffix):
            return tz
    return "America/New_York"


def make_prices(
    symbol: str,
    days: int = 300,
    end: pd.Timestamp | None = None,
    seed: int = 0,
    daily_vol: float = 0.015,
) -> pd.DataFrame:
    """Synthetic daily OHLCV bars stamped at exchange-local midnight, like yfinance."""
    end = end or pd.Timestamp.now().normalize()
    dates = pd.bdate_range(end=end, periods=days).tz_localize(_exchange_tz(symbol))
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, daily_vol, days))
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, days),
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=pd.DatetimeIndex(dates, name="Date"),
    )


def make_statements(years: int = 4, revenue: float = 100e9, growth: float = 0.08) -> dict[str, Any]:
    """Annual statements (newest year first, like yfinance) for a steadily growing company."""
    dates = [pd.Timestamp(f"{2025 - i}-12-31") for i in range(years)]
    income, balance, cashflow = {}, {}, {}
    for i, d in enumerate(dates):
        rev = revenue / (1 + growth) ** i
        net = rev * 0.2
        income[d] = {
            "Total Revenue": rev,
            "Cost Of Revenue": rev * 0.55,
            "Gross Profit": rev * 0.45,
            "Operating Income": rev * 0.28,
            "EBIT": rev * 0.28,
            "Interest Expense": rev * 0.01,
            "Net Income": net,
            "Reconciled Depreciation": rev * 0.04,
            "Diluted Average Shares": 2.5e9,
            "Basic Average Shares": 2.5e9,
        }
        balance[d] = {
            "Total Assets": rev * 1.5,
            "Current Assets": rev * 0.6,
            "Current Liabilities": rev * 0.4,
            "Total Liabilities Net Minority Interest": rev * 0.8,
            "Long Term Debt": rev * 0.3,
            "Total Debt": rev * 0.35,
            "Accounts Receivable": rev * 0.1,
            "Retained Earnings": rev * 0.5,
            "Stockholders Equity": rev * 0.7,
            "Common Stock Equity": rev * 0.7,
            "Ordinary Shares Number": 2.5e9,
            "Cash And Cash Equivalents": rev * 0.15,
        }
        cashflow[d] = {
            "Operating Cash Flow": net * 1.3,
            "Capital Expenditure": -rev * 0.05,
            "Free Cash Flow": net * 1.3 - rev * 0.05,
            "Cash Dividends Paid": -net * 0.3,
        }
    return {
        "income_stmt": pd.DataFrame(income),
        "balance_sheet": pd.DataFrame(balance),
        "cashflow": pd.DataFrame(cashflow),
    }


def make_context(symbol: str) -> dict[str, Any]:
    """Earnings, dividends, holders and analyst ratings in yfinance's shapes."""
    tz = _exchange_tz(symbol)
    quarters = pd.date_range(end="2026-09-30", periods=8, freq="QE")
    actual = np.linspace(1.2, 1.6, len(quarters))
    estimate = actual * np.where(np.arange(len(quarters)) % 3 == 0, 1.05, 0.97)
    earnings_history = pd.DataFrame(
        {
            "epsActual": actual,
            "epsEstimate": estimate,
            "epsDifference": actual - estimate,
            "surprisePercent": (actual - estimate) / estimate,
        },
        index=pd.Index(quarters, name="quarter"),
    )
    report_dates = (quarters + pd.Timedelta(days=30)).tz_localize(tz)
    earnings_dates = pd.DataFrame(
        {
            "EPS Estimate": estimate,
            "Reported EPS": actual,
            "Surprise(%)": (actual / estimate - 1) * 100,
        },
        index=pd.DatetimeIndex(report_dates, name="Earnings Date"),
    ).sort_index(ascending=False)
    dividend_dates = pd.date_range(end="2026-08-15", periods=12, freq="QS-FEB").tz_localize(tz)
    dividends = pd.Series(
        np.linspace(0.20, 0.26, len(dividend_dates)), index=dividend_dates, name="Dividends"
    )
    holders = pd.DataFrame(
        {
            "Date Reported": pd.Timestamp("2026-06-30"),
            "Holder": [f"Fund {i}" for i in range(1, 11)],
            "pctHeld": np.linspace(0.08, 0.01, 10),
            "Shares": np.linspace(2e8, 2.5e7, 10).astype(int),
            "Value": np.linspace(4e10, 5e9, 10).astype(int),
            "pctChange": np.linspace(0.05, -0.04, 10),
        }
    )
    recommendations = pd.DataFrame(
        {
            "period": ["0m", "-1m", "-2m", "-3m"],
            "strongBuy": [8, 8, 7, 7],
            "buy": [20, 19, 19, 18],
            "hold": [10, 11, 11, 12],
            "sell": [1, 1, 2, 2],
            "strongSell": [0, 0, 1, 1],
        }
    )
    upgrades = pd.DataFrame(
        {
            "Firm": ["Broker A", "Broker B", "Broker C"],
            "ToGrade": ["Buy", "Overweight", "Hold"],
            "FromGrade": ["Hold", "Equal-Weight", "Buy"],
            "Action": ["up", "up", "down"],
            "currentPriceTarget": [250.0, 240.0, np.nan],
        },
        index=pd.DatetimeIndex(
            pd.date_range(end="2026-10-01", periods=3, freq="MS"), name="GradeDate"
        ),
    )
    return {
        "earnings_history": earnings_history,
        "earnings_dates": earnings_dates,
        "dividends": dividends,
        "institutional_holders": holders,
        "mutualfund_holders": holders.assign(Holder=[f"Index Fund {i}" for i in range(1, 11)]),
        "recommendations": recommendations,
        "upgrades_downgrades": upgrades,
    }


def mock_report_data(ticker: str = "AAPL") -> dict:
    """Create minimal report data for testing."""
    return {
        "ticker": ticker,
        "generated_at": datetime.now().isoformat(),
        "info": {"trailingPE": 28.5, "marketCap": 3000000000000},
        "scoring": {"composite_score": 72.5},
        "price_data": {"latest": {"close": 180.0}},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "risk_analysis": {},
        "valuation_analysis": {},
    }


def make_scoring(ticker="AAPL", score=60.0, signal="Hold", valuation=50.0, preset="default"):
    return ScoringResult(
        ticker=ticker,
        composite_score=score,
        signal=signal,
        confidence="Medium",
        confidence_score=0.7,
        technical=DimensionResult("technical", 55.0),
        valuation=DimensionResult("valuation", valuation),
        config_name=preset,
    )


def make_report(price=100.0, currency="USD"):
    return {"info": {"current_price": price, "currency": currency}}


def make_flag(title, severity="medium"):
    return RedFlag(severity=severity, title=title, detail="", rule="test")
