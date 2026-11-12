"""
Tests for the analysis pipeline and the data-layer fixes it relies on:
cache expiry, per-run fetch de-duplication, home-market benchmarks,
cross-timezone return alignment, and freshness warnings.
"""

import logging
import os
import threading
import time

import pandas as pd
import pytest

from src.config import AnalysisConfig, set_config
from src.data_fetcher import DataFetcher, normalize_bar_index
from src.markets import benchmark_for, benchmark_name
from src.pipeline import AnalysisOptions, analyze_ticker
from src.utils.concurrency import run_concurrently
from src.utils.financial import align_daily_returns, convert_annual_to_daily_rate
from tests.conftest import make_prices

# ============================================================
# Pipeline
# ============================================================


class TestAnalyzeTicker:
    def test_produces_scored_report(self, fake_market, tmp_path):
        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.scoring is not None
        assert bundle.report["scoring"]["composite_score"] == pytest.approx(
            bundle.scoring.composite_score, abs=0.1
        )
        assert bundle.report["technical_analysis"] is not None
        assert bundle.report["risk_analysis"]["market_risk"]["beta"] is not None

    def test_us_ticker_uses_sp500_benchmark(self, fake_market, tmp_path):
        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.report["benchmark"] == "^GSPC"

    def test_oslo_ticker_gets_beta_against_osebx(self, fake_market, tmp_path):
        bundle = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path)))

        market_risk = bundle.report["risk_analysis"]["market_risk"]
        assert bundle.report["benchmark"] == "OSEBX.OL"
        assert market_risk["beta"] is not None

    def test_unavailable_local_benchmark_falls_back_to_default(self, fake_market, tmp_path):
        fake_market.failing.add("OSEBX.OL")

        bundle = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.report["benchmark"] == "^GSPC"

    def test_prices_fetched_once_per_run_without_cache(self, fake_market, tmp_path):
        options = AnalysisOptions(use_cache=False)

        analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), options)

        assert fake_market.calls[("history", "AAPL")] == 1
        assert fake_market.calls[("info", "AAPL")] == 1

    def test_skipping_context_avoids_news_holders_ratings(self, fake_market, tmp_path):
        options = AnalysisOptions(include_context=False)

        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), options)

        assert not {"news", "holders", "analyst_ratings"} & bundle.report.keys()
        assert fake_market.calls[("news", "AAPL")] == 0
        assert bundle.scoring is not None

    def test_scoring_config_is_applied(self, fake_market, tmp_path):
        from src.scoring import ScoringConfig

        options = AnalysisOptions(scoring_config=ScoringConfig.value_investor())

        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), options)

        assert bundle.report["scoring"]["metadata"]["config_name"] == "value"

    def test_stale_last_price_bar_is_flagged(self, fake_market, tmp_path, price_factory):
        old_end = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
        fake_market.price_overrides["HALTED"] = price_factory("HALTED", end=old_end)

        bundle = analyze_ticker("HALTED", DataFetcher(cache_dir=str(tmp_path)))

        assert any("Latest price bar" in w for w in bundle.freshness_warnings)

    def test_fresh_data_has_no_warnings(self, fake_market, tmp_path):
        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.freshness_warnings == []
        assert "prices" in bundle.report["data_freshness"]["fetched_at"]

    def test_unknown_ticker_records_errors_without_raising(self, fake_market, tmp_path):
        fake_market.price_overrides["NOPE"] = pd.DataFrame()

        bundle = analyze_ticker("NOPE", DataFetcher(cache_dir=str(tmp_path)))

        assert "technical_analysis" in bundle.errors
        assert bundle.report["technical_analysis"] is None

    @pytest.mark.parametrize("level, traceback", [(logging.WARNING, False), (logging.DEBUG, True)])
    def test_step_errors_log_the_traceback_only_when_verbose(
        self, fake_market, tmp_path, caplog, level, traceback
    ):
        fake_market.price_overrides["NOPE"] = pd.DataFrame()
        caplog.set_level(level, logger="src.pipeline")

        analyze_ticker("NOPE", DataFetcher(cache_dir=str(tmp_path)))

        records = [r for r in caplog.records if "Error processing technical_analysis" in r.message]
        assert records
        assert bool(records[0].exc_info) is traceback


# ============================================================
# DataFetcher cache expiry
# ============================================================


def _age_file(path, hours: float):
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


class TestCacheExpiry:
    def test_fresh_cache_skips_network(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.fetch_ticker("AAPL", period="1y")

        fetcher.fetch_ticker("AAPL", period="1y")

        assert fake_market.calls[("history", "AAPL")] == 1

    def test_expired_price_cache_is_refetched(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.fetch_ticker("AAPL", period="1y")
        _age_file(tmp_path / "AAPL" / "cache" / "prices_1y_1d.csv", hours=13)

        fetcher.fetch_ticker("AAPL", period="1y")

        assert fake_market.calls[("history", "AAPL")] == 2

    def test_expired_json_cache_is_refetched(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.get_ticker_info("AAPL")
        _age_file(tmp_path / "AAPL" / "cache" / "info.json", hours=25)

        fetcher.get_ticker_info("AAPL")

        assert fake_market.calls[("info", "AAPL")] == 2

    def test_failed_refresh_falls_back_to_expired_price_cache(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        original = fetcher.fetch_ticker("AAPL", period="1y")
        _age_file(tmp_path / "AAPL" / "cache" / "prices_1y_1d.csv", hours=48)
        fake_market.failing.add("AAPL")

        fallback = fetcher.fetch_ticker("AAPL", period="1y")

        assert len(fallback) == len(original)

    def test_empty_refresh_falls_back_to_expired_price_cache(self, fake_market, tmp_path):
        # yfinance reports some connection failures as an empty history
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        original = fetcher.fetch_ticker("AAPL", period="1y")
        _age_file(tmp_path / "AAPL" / "cache" / "prices_1y_1d.csv", hours=48)
        fake_market.price_overrides["AAPL"] = pd.DataFrame()

        fallback = fetcher.fetch_ticker("AAPL", period="1y")

        assert len(fallback) == len(original)

    def test_empty_history_without_cache_raises(self, fake_market, tmp_path):
        fake_market.price_overrides["NOPE"] = pd.DataFrame()

        with pytest.raises(ValueError, match="No data returned"):
            DataFetcher(cache_dir=str(tmp_path)).fetch_ticker("NOPE")

    def test_failed_refresh_falls_back_to_expired_info_cache(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.get_ticker_info("AAPL")
        _age_file(tmp_path / "AAPL" / "cache" / "info.json", hours=48)
        fake_market.failing.add("AAPL")

        info = fetcher.get_ticker_info("AAPL")

        assert info["symbol"] == "AAPL"

    def test_expired_cache_fallback_is_reported_as_warning(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        analyze_ticker("AAPL", fetcher)
        _age_file(tmp_path / "AAPL" / "cache" / "info.json", hours=24 * 5)
        fake_market.failing.add("AAPL")

        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)))

        assert any(w.startswith("info data is 5 days old") for w in bundle.freshness_warnings)

    def test_zero_ttl_never_expires(self, fake_market, tmp_path):
        set_config(AnalysisConfig(cache_ttl_hours={"info": 0}))
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.get_ticker_info("AAPL")
        _age_file(tmp_path / "AAPL" / "cache" / "info.json", hours=24 * 365)

        fetcher.get_ticker_info("AAPL")

        assert fake_market.calls[("info", "AAPL")] == 1

    def test_partial_ttl_override_keeps_other_defaults(self):
        config = AnalysisConfig(cache_ttl_hours={"info": 1})

        assert config.cache_ttl_hours["info"] == 1
        assert config.cache_ttl_hours["prices"] == 12


class TestFailedRefreshKeepsCache:
    """yfinance hides most failures behind empty results instead of raising."""

    def test_empty_statements_keep_the_expired_cache(self, fake_market, tmp_path):
        from tests.conftest import make_statements

        fake_market.attribute_overrides["AAPL"] = make_statements()
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        assert not fetcher.fetch_fundamentals("AAPL")["income_stmt_annual"].empty
        cache = tmp_path / "AAPL" / "cache" / "fundamentals.json"
        _age_file(cache, hours=24 * 30)
        aged = cache.stat().st_mtime
        fake_market.attribute_overrides["AAPL"] = {}  # throttled: empty frames

        refreshed = fetcher.fetch_fundamentals("AAPL")

        assert not refreshed["income_stmt_annual"].empty
        assert cache.stat().st_mtime == aged  # still reads as stale

    def test_empty_statements_without_a_cache_are_cached(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.fetch_fundamentals("FUND")
        fetcher.fetch_fundamentals("FUND")
        assert fake_market.calls[("income_stmt", "FUND")] == 1

    def test_an_empty_cache_is_retried_after_half_a_day(self, fake_market, tmp_path):
        # A throttled first fetch would otherwise leave no statements for a week
        from tests.conftest import make_statements

        fetcher = DataFetcher(cache_dir=str(tmp_path))
        assert fetcher.fetch_fundamentals("AAPL")["income_stmt_annual"].empty
        _age_file(tmp_path / "AAPL" / "cache" / "fundamentals.json", hours=13)
        fake_market.attribute_overrides["AAPL"] = make_statements()

        assert not fetcher.fetch_fundamentals("AAPL")["income_stmt_annual"].empty

    def test_no_statements_means_no_piotroski_score(self):
        from src.analysis.fundamental import FundamentalAnalyzer

        empty = {k: pd.DataFrame() for k in ("income_stmt_annual", "balance_sheet_annual")}
        empty["cash_flow_annual"] = pd.DataFrame()
        assert FundamentalAnalyzer({}, empty).calculate_piotroski_f_score() is None

    def test_near_empty_info_falls_back_to_expired_cache(self, fake_market, tmp_path, monkeypatch):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fetcher.get_ticker_info("AAPL")
        _age_file(tmp_path / "AAPL" / "cache" / "info.json", hours=48)
        throttled = property(lambda self: {"trailingPegRatio": None})
        monkeypatch.setattr(type(fake_market.ticker("AAPL")), "info", throttled)

        info = fetcher.get_ticker_info("AAPL")

        assert info["currency"] == "USD" and info["market_cap"]

    def test_failed_dividends_fall_back_to_expired_cache(self, fake_market, tmp_path):
        dates = pd.date_range("2024-01-15", periods=8, freq="QS", tz="America/New_York")
        fake_market.attribute_overrides["AAPL"] = {"dividends": pd.Series(0.25, index=dates)}
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        assert len(fetcher.fetch_dividends("AAPL")["dividends"]) == 8
        _age_file(tmp_path / "AAPL" / "cache" / "dividends.json", hours=24 * 30)
        fake_market.failing.add("AAPL")

        assert len(fetcher.fetch_dividends("AAPL")["dividends"]) == 8


def test_tests_cannot_reach_yahoo(tmp_path):
    # Without fake_market, the autouse _isolated fixture blocks yfinance
    with pytest.raises(RuntimeError, match="use the fake_market fixture"):
        DataFetcher(cache_dir=str(tmp_path)).fetch_ticker("AAPL")


class TestPriceIndex:
    """Fresh and cached bars share one index: tz-naive trading dates."""

    @pytest.mark.parametrize("symbol", ["EQNR.OL", "AAPL", "HSBA.L"])
    def test_cached_bars_keep_the_trading_date(self, fake_market, tmp_path, symbol):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fresh = fetcher.fetch_ticker(symbol, period="1y")

        cached = fetcher.fetch_ticker(symbol, period="1y")

        assert fake_market.calls[("history", symbol)] == 1
        assert fresh.index.tz is None
        pd.testing.assert_index_equal(cached.index, fresh.index, check_names=False)
        exchange_last = make_prices(symbol).index[-1]  # exchange-local midnight
        assert cached.index[-1] == exchange_last.tz_localize(None)

    def test_expired_cache_fallback_has_the_same_index(self, fake_market, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        fresh = fetcher.fetch_ticker("EQNR.OL", period="1y")
        _age_file(tmp_path / "EQNR.OL" / "cache" / "prices_1y_1d.csv", hours=48)
        fake_market.failing.add("EQNR.OL")

        fallback = fetcher.fetch_ticker("EQNR.OL", period="1y")

        pd.testing.assert_index_equal(fallback.index, fresh.index, check_names=False)

    def test_reads_caches_written_with_exchange_offsets(self, tmp_path):
        # Caches written before the fix hold "2026-03-27 00:00:00+01:00" stamps,
        # with the offset changing at DST
        stamps = pd.DatetimeIndex(["2026-03-27", "2026-03-30", "2026-11-04"]).tz_localize(
            "Europe/Oslo"
        )
        bars = pd.DataFrame(
            {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1},
            index=pd.DatetimeIndex(stamps, name="Date"),
        )
        cache_dir = tmp_path / "EQNR.OL" / "cache"
        cache_dir.mkdir(parents=True)
        bars.to_csv(cache_dir / "prices_1y_1d.csv")

        loaded = DataFetcher(cache_dir=str(tmp_path)).fetch_ticker("EQNR.OL", period="1y")

        assert list(loaded.index) == list(
            pd.DatetimeIndex(["2026-03-27", "2026-03-30", "2026-11-04"])
        )

    def test_intraday_bars_keep_their_time_in_utc(self):
        stamps = pd.DatetimeIndex(["2026-11-04 09:00", "2026-11-04 09:05"]).tz_localize(
            "Europe/Oslo"
        )
        bars = pd.DataFrame({"Close": [1.0, 2.0]}, index=stamps)

        out = normalize_bar_index(bars, "5m")

        assert str(out.index.tz) == "UTC"
        assert out.index[0] == pd.Timestamp("2026-11-04 08:00", tz="UTC")


# ============================================================
# Benchmarks and return alignment
# ============================================================


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [
        pytest.param("AAPL", "^GSPC", id="us-listing"),
        pytest.param("EQNR", "^GSPC", id="us-adr"),
        pytest.param("EQNR.OL", "OSEBX.OL", id="oslo"),
        pytest.param("bp.l", "^FTSE", id="london-lowercase"),
        pytest.param("SAP.DE", "^GDAXI", id="xetra"),
        pytest.param("FOO.XX", "^GSPC", id="unmapped-suffix"),
    ],
)
def test_benchmark_for(default_config, ticker, expected):
    assert benchmark_for(ticker) == expected


def test_benchmark_override_from_config():
    set_config(AnalysisConfig(benchmark_by_suffix={".OL": "OBX.OL"}))
    try:
        assert benchmark_for("EQNR.OL") == "OBX.OL"
    finally:
        set_config(AnalysisConfig())


def test_benchmark_name_falls_back_to_symbol():
    assert benchmark_name("^GSPC") == "S&P 500"
    assert benchmark_name("XYZ.OL") == "XYZ.OL"


class TestAlignDailyReturns:
    def test_aligns_across_exchange_timezones(self, price_factory):
        oslo = price_factory("EQNR.OL")["Close"].pct_change().dropna()
        new_york = price_factory("AAPL")["Close"].pct_change().dropna()

        aligned = align_daily_returns(oslo, new_york)

        assert len(aligned) == len(oslo)

    def test_aligns_utc_cached_data_to_trading_dates(self, price_factory):
        oslo = price_factory("EQNR.OL")["Close"].pct_change().dropna()
        oslo_from_cache = oslo.copy()
        oslo_from_cache.index = oslo.index.tz_convert("UTC")
        new_york = price_factory("AAPL")["Close"].pct_change().dropna()

        aligned = align_daily_returns(oslo_from_cache, new_york)

        assert len(aligned) == len(oslo)
        assert aligned.index[0] == oslo.index[0].tz_localize(None)


def test_daily_risk_free_rate_from_decimal_annual_rate():
    assert convert_annual_to_daily_rate(0.04) == pytest.approx(0.0001556, rel=1e-3)


# ============================================================
# Concurrency
# ============================================================


def test_run_concurrently_captures_per_item_errors():
    def _square(x: int) -> int:
        if x == 3:
            raise ValueError("bad item")
        return x * x

    outcomes = {
        item: (result, error)
        for item, result, error in run_concurrently(_square, [1, 2, 3], workers=3)
    }

    assert outcomes[2] == (4, None)
    assert isinstance(outcomes[3][1], ValueError)


def test_zero_price_bars_are_cleaned(fake_market, price_factory, tmp_path):
    # Yahoo fund NAV series sometimes carry a bar with Open/High/Low = 0
    prices = price_factory("FUND.IR", days=60)
    prices.iloc[10, prices.columns.get_loc("Low")] = 0.0
    prices.iloc[20, prices.columns.get_loc("Close")] = 0.0
    fake_market.price_overrides["FUND.IR"] = prices
    fetcher = DataFetcher(cache_dir=str(tmp_path))

    for use_cache in (False, True):  # fresh, then from the cache file
        cleaned = fetcher.fetch_ticker("FUND.IR", period="1y", use_cache=use_cache)
        assert len(cleaned) == 59  # the zero-Close bar is dropped
        assert (cleaned[["Open", "High", "Low", "Close"]] > 0).all().all()
        assert cleaned["Low"].iloc[10] == cleaned["Close"].iloc[10]


def test_none_from_yfinance_is_an_empty_resource(fake_market, tmp_path):
    fake_market.attribute_overrides["NEW"] = {"earnings_dates": None}
    earnings = DataFetcher(cache_dir=str(tmp_path)).fetch_earnings("NEW", use_cache=False)
    assert earnings["earnings_dates"].empty


@pytest.mark.parametrize("stop", ["interrupt", "close"])
def test_run_concurrently_drops_queued_items_when_stopped(stop):
    """Ctrl-C (or a caller that stops early) used to wait for every queued ticker."""
    started = []
    lock = threading.Lock()

    def _slow(x: int) -> int:
        with lock:
            started.append(x)
        time.sleep(0.05)
        return x

    results = run_concurrently(_slow, range(40), workers=2)
    next(results)
    if stop == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            results.throw(KeyboardInterrupt)
    else:
        results.close()
    time.sleep(0.2)
    assert len(started) < 12
