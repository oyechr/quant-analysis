"""
Price-only Backtest

Walks forward through month-ends. At each one, every ticker is scored using
only the prices up to that day, and the returns over the following months
are recorded, raw and relative to the ticker's home benchmark.

Signals tested:
  - composite: the real scorer run on the technical and risk dimensions only
    (it rescales the weights over the dimensions it has), so its Buy/Hold/Sell
    bands are the ones `score` and `vet` use
  - technical, risk: the two dimension scores
  - momentum: 12-minus-1-month return (the screen's factor)
  - low_vol: 1 / annualized volatility (the screen's factor)

Fundamental and valuation scores are left out on purpose: Yahoo serves the
latest restated statements with no publication dates, so scoring a past date
with them would use information nobody had then.

Prices are Yahoo's adjusted closes (splits and dividends), so returns are
total returns. A signal is assumed to be traded at the close it was computed
from, with no costs.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd

from ..analysis.risk import RiskMetrics
from ..analysis.technical import TechnicalAnalyzer
from ..data_fetcher import DataFetcher
from ..discovery.factor_ranking import inverse_volatility, momentum_12_1
from ..markets import benchmark_for
from ..scoring import ScoringConfig, StockScorer
from ..utils.concurrency import DEFAULT_WORKERS, run_concurrently
from ..utils.financial import trading_dates

logger = logging.getLogger(__name__)

LOOKBACK_BARS = 252  # one year: the 200-day SMA and the one-year risk window
DEFAULT_HORIZONS = (1, 3, 6)  # months
SIGNALS = ("composite", "technical", "risk", "momentum", "low_vol")

# yfinance only takes these periods; the history must cover the test plus a lookback year
_PERIODS = (("2y", 2), ("5y", 5), ("10y", 10))


@dataclass
class BacktestResult:
    universe: str
    preset: str
    years: int
    horizons: tuple[int, ...]
    months: List[str]
    observations: pd.DataFrame
    errors: Dict[str, str] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def tickers(self) -> int:
        return int(self.observations["ticker"].nunique()) if not self.observations.empty else 0


def history_period(years: int) -> str:
    """The shortest Yahoo period covering `years` of tests plus a lookback year."""
    for period, span in _PERIODS:
        if years + 1 <= span:
            return period
    return "max"


def backtest_months(years: int, today: Optional[date] = None) -> List[pd.Period]:
    """The last `years` complete calendar months, oldest first."""
    last = pd.Period(today or date.today(), freq="M") - 1
    return [last - k for k in range(years * 12 - 1, -1, -1)]


def month_end_positions(index: pd.DatetimeIndex) -> pd.Series:
    """Month -> position of that month's last bar."""
    months = trading_dates(index).to_period("M")
    return pd.Series(range(len(index)), index=months).groupby(level=0).last()


def score_window(
    window: pd.DataFrame,
    benchmark_window: pd.DataFrame,
    benchmark_ticker: str,
    config: ScoringConfig,
) -> Dict[str, Any]:
    """Every signal from one lookback window of prices."""
    technical = TechnicalAnalyzer(window)
    technical.calculate_all_indicators()
    risk = RiskMetrics(benchmark_ticker=benchmark_ticker).calculate_scoring_metrics(
        window, benchmark_window
    )
    result = StockScorer(config=config).score(
        {
            "ticker": "",
            "info": {},
            "technical_analysis": technical.get_summary(),
            "risk_analysis": risk,
        }
    )
    close = window["Close"]
    return {
        "composite": result.composite_score if result.dimensions_available else None,
        "signal": result.signal if result.dimensions_available else None,
        "technical": result.technical.score if result.technical else None,
        "risk": result.risk.score if result.risk else None,
        "momentum": momentum_12_1(close),
        "low_vol": inverse_volatility(close),
    }


def ticker_observations(
    ticker: str,
    prices: pd.DataFrame,
    benchmark: pd.DataFrame,
    benchmark_ticker: str,
    months: Sequence[pd.Period],
    horizons: Sequence[int],
    config: ScoringConfig,
) -> List[Dict[str, Any]]:
    """One row per test month: the signals at that month-end and the forward returns."""
    close = prices["Close"]
    ends = month_end_positions(pd.DatetimeIndex(prices.index))
    bench_close = benchmark["Close"]
    bench_dates = trading_dates(pd.DatetimeIndex(benchmark.index))
    bench_ends = month_end_positions(pd.DatetimeIndex(benchmark.index))
    last_month = months[-1]

    rows: List[Dict[str, Any]] = []
    for month in months:
        if month not in ends.index:
            continue
        i = int(ends[month])
        if i + 1 < LOOKBACK_BARS:
            continue
        window = prices.iloc[i + 1 - LOOKBACK_BARS : i + 1]
        # The benchmark up to the same trading date (exchanges keep different holidays)
        j = int(bench_dates.searchsorted(trading_dates(window.index[-1:])[0], side="right"))
        benchmark_window = benchmark.iloc[max(0, j - LOOKBACK_BARS) : j]

        row: Dict[str, Any] = {
            "month": str(month),
            "ticker": ticker,
            "benchmark": benchmark_ticker,
            **score_window(window, benchmark_window, benchmark_ticker, config),
        }
        for h in horizons:
            target = month + h
            ret = excess = None
            # Only complete months: the current month's last bar isn't its month-end
            if target <= last_month and target in ends.index:
                ret = float(close.iloc[int(ends[target])] / close.iloc[i] - 1)
                if month in bench_ends.index and target in bench_ends.index:
                    bench_ret = float(
                        bench_close.iloc[int(bench_ends[target])]
                        / bench_close.iloc[int(bench_ends[month])]
                        - 1
                    )
                    excess = ret - bench_ret
            row[f"ret_{h}m"] = ret
            row[f"excess_{h}m"] = excess
        rows.append(row)
    return rows


def run_backtest(
    tickers: Sequence[str],
    fetcher: Optional[DataFetcher] = None,
    years: int = 5,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    config: Optional[ScoringConfig] = None,
    use_cache: bool = True,
    workers: int = DEFAULT_WORKERS,
    universe_label: str = "custom",
    today: Optional[date] = None,
    progress: Optional[Callable[[str, Optional[Exception]], None]] = None,
) -> BacktestResult:
    """Score every ticker at every month-end of the last `years` years."""
    fetcher = fetcher or DataFetcher()
    config = config or ScoringConfig()
    horizons = tuple(sorted(set(horizons)))
    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    months = backtest_months(years, today)
    period = history_period(years)

    # Each benchmark once, before the tickers that share it
    benchmarks: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, str] = {}
    for symbol in dict.fromkeys(benchmark_for(t) for t in tickers):
        try:
            benchmarks[symbol] = fetcher.fetch_ticker(symbol, period=period, use_cache=use_cache)
        except Exception as e:
            errors[symbol] = f"benchmark unavailable: {e}"

    def run(ticker: str) -> List[Dict[str, Any]]:
        symbol = benchmark_for(ticker)
        if symbol not in benchmarks:
            raise ValueError(f"benchmark {symbol} unavailable")
        prices = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)
        if len(prices) <= LOOKBACK_BARS:
            raise ValueError(f"only {len(prices)} days of prices")
        return ticker_observations(
            ticker, prices, benchmarks[symbol], symbol, months, horizons, config
        )

    rows: List[Dict[str, Any]] = []
    for ticker, result, error in run_concurrently(run, tickers, workers=workers):
        if error is not None or result is None:
            errors[ticker] = str(error or "no result")
        else:
            rows.extend(result)
        if progress:
            progress(ticker, error)

    return BacktestResult(
        universe=universe_label,
        preset=config.name,
        years=years,
        horizons=horizons,
        months=[str(m) for m in months],
        observations=pd.DataFrame(rows),
        errors=errors,
    )
