"""
Shared fixtures.

`fake_yahoo` replaces yfinance.Ticker (the network boundary) with a synthetic
in-memory market so the real DataFetcher, cache, analyzers, and scorer run
offline.
"""

import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Optional

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


class FakeMarket:
    """Configurable stand-in for Yahoo Finance; counts calls per (attribute, symbol)."""

    def __init__(self):
        self.calls: Counter = Counter()
        self.price_overrides: Dict[str, pd.DataFrame] = {}
        self.failing: set[str] = set()
        self.info_overrides: Dict[str, dict] = {}

    def ticker(self, symbol: str) -> "FakeTicker":
        return FakeTicker(symbol.upper(), self)


class FakeTicker:
    def __init__(self, symbol: str, market: FakeMarket):
        self.symbol = symbol
        self._market = market

    def _check(self, attr: str):
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

    def __getattr__(self, name: str):
        # Statements, earnings, holders, ratings: empty frames; news: empty list
        self._check(name)
        if name == "news":
            return []
        if name in ("dividends", "splits"):
            return pd.Series(dtype=float)
        return pd.DataFrame()


@pytest.fixture
def default_config():
    """Isolate tests from any local config.json."""
    config = AnalysisConfig()
    set_config(config)
    yield config
    set_config(AnalysisConfig())


@pytest.fixture
def fake_market(monkeypatch, default_config) -> FakeMarket:
    market = FakeMarket()
    monkeypatch.setattr("src.data_fetcher.yf.Ticker", market.ticker)
    return market


@pytest.fixture
def price_factory() -> Callable[..., pd.DataFrame]:
    return make_prices
