"""
Tests for the analysis pipeline and the data-layer fixes it relies on:
cache expiry, per-run fetch de-duplication, home-market benchmarks,
cross-timezone return alignment, and freshness warnings.
"""

import os
import time

import pandas as pd
import pytest

from src.config import AnalysisConfig, set_config
from src.data_fetcher import DataFetcher
from src.markets import benchmark_for, benchmark_name
from src.pipeline import AnalysisOptions, analyze_ticker
from src.utils.concurrency import run_concurrently
from src.utils.financial import align_daily_returns, convert_annual_to_daily_rate

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
