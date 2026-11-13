"""
Shared fixtures.

`fake_market` replaces yfinance.Ticker, Industry and Sector (the network
boundary) with a synthetic in-memory market so the real DataFetcher, cache,
analyzers, and scorer run offline. `_isolated` (autouse) gives every test
its own working directory and default settings, and blocks the network.
"""

import socket
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.config import AnalysisConfig, set_config
from tests.helpers import make_context, make_prices, make_statements

SAMPLE_TICKERS = ("AAPL", "EXE.TO", "GJF.OL")


class FakeMarket:
    """Configurable stand-in for Yahoo Finance; counts calls per (attribute, symbol)."""

    def __init__(self) -> None:
        self.calls: Counter[tuple[str, str]] = Counter()
        self.price_overrides: dict[str, pd.DataFrame] = {}
        self.failing: set[str] = set()
        self.info_overrides: dict[str, dict[str, Any]] = {}
        # symbol -> attribute (e.g. "cashflow", "income_stmt") -> value
        self.attribute_overrides: dict[str, dict[str, Any]] = {}
        # Yahoo industry/sector key -> top company symbols (yf.Industry/Sector(key).top_companies)
        self.industries: dict[str, list[str]] = {}
        self.sectors: dict[str, list[str]] = {}

    def ticker(self, symbol: str) -> FakeTicker:
        return FakeTicker(symbol.upper(), self)

    def industry(self, key: str) -> FakeGroup:
        return FakeGroup("industry", key, self)

    def sector(self, key: str) -> FakeGroup:
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


def _no_yahoo(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("A test tried to reach Yahoo; use the fake_market fixture")


def _no_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("A test tried to open a network connection")


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Every test runs in its own temp directory, with default settings and no
    network. Commands read portfolio/, watchlist.toml and config.json, and
    write data/, relative to the working directory; a test run from the repo
    once wrote into the real score history. yfinance goes through curl_cffi,
    which a socket block doesn't catch, so its entry points raise too until
    `fake_market` replaces them.
    """
    monkeypatch.chdir(tmp_path)
    set_config(AnalysisConfig())
    for name in ("Ticker", "Industry", "Sector"):
        monkeypatch.setattr(f"src.data_fetcher.yf.{name}", _no_yahoo)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    yield
    set_config(AnalysisConfig())


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
        {
            "id": "1",
            "content": {
                "title": "Results beat estimates",
                "pubDate": "2026-10-02T12:00:00Z",
                "provider": {"displayName": "Wire"},
                "canonicalUrl": {"url": "https://example.com/results"},
            },
        }
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
