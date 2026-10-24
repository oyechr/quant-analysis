"""
Shared fixtures.

`fake_market` replaces yfinance.Ticker, Industry and Sector (the network
boundary) with a synthetic in-memory market so the real DataFetcher, cache,
analyzers, and scorer run offline.
"""

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import AnalysisConfig, set_config  # noqa: E402

_EXCHANGE_TZ = {".OL": "Europe/Oslo", ".L": "Europe/London"}


def _exchange_tz(symbol: str) -> str:
    for suffix, tz in _EXCHANGE_TZ.items():
        if symbol.upper().endswith(suffix):
            return tz
    return "America/New_York"


def make_prices(
    symbol: str,
    days: int = 300,
    end: Optional[pd.Timestamp] = None,
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


def make_statements(years: int = 4, revenue: float = 100e9, growth: float = 0.08) -> Dict[str, Any]:
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


def make_context(symbol: str) -> Dict[str, Any]:
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


SAMPLE_TICKERS = ("AAPL", "EXE.TO", "GJF.OL")


class FakeMarket:
    """Configurable stand-in for Yahoo Finance; counts calls per (attribute, symbol)."""

    def __init__(self) -> None:
        self.calls: Counter[tuple[str, str]] = Counter()
        self.price_overrides: Dict[str, pd.DataFrame] = {}
        self.failing: set[str] = set()
        self.info_overrides: Dict[str, Dict[str, Any]] = {}
        # symbol -> attribute (e.g. "cashflow", "income_stmt") -> value
        self.attribute_overrides: Dict[str, Dict[str, Any]] = {}
        # Yahoo industry/sector key -> top company symbols (yf.Industry/Sector(key).top_companies)
        self.industries: Dict[str, List[str]] = {}
        self.sectors: Dict[str, List[str]] = {}

    def ticker(self, symbol: str) -> "FakeTicker":
        return FakeTicker(symbol.upper(), self)

    def industry(self, key: str) -> "FakeGroup":
        return FakeGroup("industry", key, self)

    def sector(self, key: str) -> "FakeGroup":
        return FakeGroup("sector", key, self)


class FakeGroup:
    """Stand-in for yf.Industry / yf.Sector."""

    def __init__(self, kind: str, key: str, market: FakeMarket) -> None:
        self.kind = kind
        self.key = key
        self._market = market

    @property
    def top_companies(self) -> pd.DataFrame:
        self._market.calls[(self.kind, self.key)] += 1
        if self.key in self._market.failing:
            raise ConnectionError(f"simulated outage for {self.kind} {self.key}")
        groups = self._market.industries if self.kind == "industry" else self._market.sectors
        symbols = groups.get(self.key, [])
        return pd.DataFrame(
            {"name": [f"{t} Corp" for t in symbols]}, index=pd.Index(symbols, name="symbol")
        )


class FakeTicker:
    def __init__(self, symbol: str, market: FakeMarket) -> None:
        self.symbol = symbol
        self._market = market

    def _check(self, attr: str) -> None:
        self._market.calls[(attr, self.symbol)] += 1
        if self.symbol in self._market.failing:
            raise ConnectionError(f"simulated outage for {self.symbol}")

    def history(self, period=None, interval="1d", start=None, end=None) -> pd.DataFrame:
        self._check("history")
        if self.symbol in self._market.price_overrides:
            return self._market.price_overrides[self.symbol]
        return make_prices(self.symbol, seed=sum(map(ord, self.symbol)))

    @property
    def info(self) -> dict:
        self._check("info")
        base = {
            "symbol": self.symbol,
            "longName": f"{self.symbol} Corp",
            "sector": "Technology",
            "industry": "Software",
            "marketCap": 50_000_000_000,
            "currency": "NOK" if self.symbol.endswith(".OL") else "USD",
            "trailingPE": 20.0,
            "priceToBook": 4.0,
            "returnOnEquity": 0.2,
            "debtToEquity": 80.0,
            "averageVolume": 2_000_000,
        }
        return {**base, **self._market.info_overrides.get(self.symbol, {})}

    def __getattr__(self, name: str) -> Any:
        # Statements, earnings, holders, ratings: empty frames unless overridden;
        # news: empty list
        self._check(name)
        overrides = self._market.attribute_overrides.get(self.symbol, {})
        if name in overrides:
            return overrides[name]
        if name == "news":
            return []
        if name in ("dividends", "splits"):
            return pd.Series(dtype=float)
        return pd.DataFrame()


@pytest.fixture
def default_config() -> Iterator[AnalysisConfig]:
    """Isolate tests from any local config.json."""
    config = AnalysisConfig()
    set_config(config)
    yield config
    set_config(AnalysisConfig())


@pytest.fixture
def fake_market(monkeypatch: pytest.MonkeyPatch, default_config: AnalysisConfig) -> FakeMarket:
    market = FakeMarket()
    monkeypatch.setattr("src.data_fetcher.yf.Ticker", market.ticker)
    monkeypatch.setattr("src.data_fetcher.yf.Industry", market.industry)
    monkeypatch.setattr("src.data_fetcher.yf.Sector", market.sector)
    return market


@pytest.fixture(scope="session")
def sample_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A data dir with full reports for SAMPLE_TICKERS, built once by the real pipeline."""
    from src.reporting import ReportGenerator

    data_dir = tmp_path_factory.mktemp("sample_data")
    market = FakeMarket()
    news = [
        {"id": "1", "content": {"title": "Results beat estimates", "provider": {"name": "Wire"}}}
    ]
    for symbol in SAMPLE_TICKERS:
        market.attribute_overrides[symbol] = {
            **make_statements(),
            **make_context(symbol),
            "news": news,
        }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.data_fetcher.yf.Ticker", market.ticker)
        mp.setattr("src.data_fetcher.yf.Industry", market.industry)
        mp.setattr("src.data_fetcher.yf.Sector", market.sector)
        set_config(AnalysisConfig())
        try:
            generator = ReportGenerator(output_dir=str(data_dir))
            for symbol in SAMPLE_TICKERS:
                generator.generate_full_report(symbol, output_format="all", use_cache=False)
        finally:
            set_config(AnalysisConfig())
    return data_dir


@pytest.fixture
def price_factory() -> Callable[..., pd.DataFrame]:
    return make_prices
