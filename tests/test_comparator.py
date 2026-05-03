"""
Tests for the TickerComparator and PortfolioView.
Uses mocked report data — no network calls.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.comparison.comparator import (
    PortfolioView,
    TickerComparator,
    _format_large_number,
    _safe_metric,
)
from src.comparison.formatters import (
    format_comparison_json,
    format_comparison_markdown,
    format_comparison_table,
    format_correlation_heatmap,
)
from src.scoring.dimensions import DimensionResult
from src.scoring.scorer import ScoringResult


# ============================================================
# Fixtures
# ============================================================


def _make_report(ticker: str, pe: float = 25.0, market_cap: float = 1e12) -> dict:
    """Build a minimal mock report dict."""
    return {
        "ticker": ticker,
        "info": {
            "trailingPE": pe,
            "forwardPE": pe * 0.9,
            "priceToBook": 10.0,
            "pegRatio": 1.5,
            "enterpriseToEbitda": 18.0,
            "freeCashflow": 5e10,
            "marketCap": market_cap,
            "revenueGrowth": 0.08,
            "returnOnEquity": 0.35,
            "dividendYield": 0.005,
            "beta": 1.2,
            "fiftyTwoWeekHigh": 200.0,
            "fiftyTwoWeekLow": 140.0,
        },
        "technical_analysis": {"rsi": 55},
        "fundamental_analysis": {"f_score": 7},
        "risk_analysis": {"sharpe": 1.5},
        "valuation_analysis": {
            "dcf_valuation": {"discount_premium_pct": -12.5},
        },
    }


def _make_scoring_result(ticker: str, score: float = 70.0) -> ScoringResult:
    """Build a minimal ScoringResult."""
    return ScoringResult(
        ticker=ticker,
        composite_score=score,
        signal="Buy",
        confidence="High",
        confidence_score=0.80,
        technical=DimensionResult(dimension="technical", score=65.0, data_coverage=0.9),
        fundamental=DimensionResult(dimension="fundamental", score=72.0, data_coverage=0.85),
        risk=DimensionResult(dimension="risk", score=68.0, data_coverage=0.75),
        valuation=DimensionResult(dimension="valuation", score=75.0, data_coverage=0.8),
    )


# ============================================================
# TickerComparator Tests
# ============================================================


class TestTickerComparatorInit:
    def test_requires_at_least_two_tickers(self):
        with pytest.raises(ValueError, match="At least 2 tickers"):
            TickerComparator(["AAPL"])

    def test_uppercases_tickers(self):
        comp = TickerComparator(["aapl", "msft"])
        assert comp.tickers == ["AAPL", "MSFT"]


class TestTickerComparatorScoring:
    @patch("src.comparison.comparator.ReportGenerator")
    def test_fetch_all(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.side_effect = [
            _make_report("AAPL"),
            _make_report("MSFT"),
        ]
        mock_gen_cls.return_value = mock_gen

        comp = TickerComparator(["AAPL", "MSFT"])
        reports = comp.fetch_all()

        assert "AAPL" in reports
        assert "MSFT" in reports
        assert mock_gen.generate_full_report.call_count == 2

    def test_score_all_without_fetch_raises(self):
        comp = TickerComparator(["AAPL", "MSFT"])
        with pytest.raises(RuntimeError, match="fetch_all"):
            comp.score_all()

    @patch("src.comparison.comparator.StockScorer")
    @patch("src.comparison.comparator.ReportGenerator")
    def test_score_all(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.side_effect = [
            _make_report("AAPL"),
            _make_report("MSFT"),
        ]
        mock_gen_cls.return_value = mock_gen

        mock_scorer = MagicMock()
        mock_scorer.score.side_effect = [
            _make_scoring_result("AAPL", 72.0),
            _make_scoring_result("MSFT", 68.0),
        ]
        mock_scorer_cls.return_value = mock_scorer

        comp = TickerComparator(["AAPL", "MSFT"])
        comp.fetch_all()
        scores = comp.score_all()

        assert "AAPL" in scores
        assert "MSFT" in scores
        assert scores["AAPL"].composite_score == 72.0

    @patch("src.comparison.comparator.StockScorer")
    @patch("src.comparison.comparator.ReportGenerator")
    def test_side_by_side_scores(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.side_effect = [
            _make_report("AAPL"),
            _make_report("MSFT"),
        ]
        mock_gen_cls.return_value = mock_gen

        mock_scorer = MagicMock()
        mock_scorer.score.side_effect = [
            _make_scoring_result("AAPL", 72.0),
            _make_scoring_result("MSFT", 68.0),
        ]
        mock_scorer_cls.return_value = mock_scorer

        comp = TickerComparator(["AAPL", "MSFT"])
        comp.fetch_all()
        comp.score_all()
        df = comp.side_by_side_scores()

        assert "AAPL" in df.columns
        assert "MSFT" in df.columns
        assert "Composite Score" in df.index


class TestRelativeValuation:
    @patch("src.comparison.comparator.ReportGenerator")
    def test_relative_valuation(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.side_effect = [
            _make_report("AAPL", pe=28.0),
            _make_report("MSFT", pe=32.0),
        ]
        mock_gen_cls.return_value = mock_gen

        comp = TickerComparator(["AAPL", "MSFT"])
        comp.fetch_all()
        df = comp.relative_valuation()

        assert "AAPL" in df.columns
        assert "P/E" in df.index
        assert df.at["P/E", "AAPL"] == 28.0


class TestCorrelationMatrix:
    def test_correlation_matrix(self):
        comp = TickerComparator(["AAPL", "MSFT"])

        # Mock fetch_ticker to return synthetic price data
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        np.random.seed(42)

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_ticker.side_effect = [
            pd.DataFrame({"Close": np.random.randn(50).cumsum() + 100}, index=dates),
            pd.DataFrame({"Close": np.random.randn(50).cumsum() + 200}, index=dates),
        ]
        comp.fetcher = mock_fetcher

        corr = comp.correlation_matrix()
        assert corr.shape == (2, 2)
        assert abs(corr.at["AAPL", "AAPL"] - 1.0) < 0.001
        assert abs(corr.at["MSFT", "MSFT"] - 1.0) < 0.001


class TestKeyMetrics:
    @patch("src.comparison.comparator.ReportGenerator")
    def test_key_metrics_table(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.side_effect = [
            _make_report("AAPL"),
            _make_report("MSFT"),
        ]
        mock_gen_cls.return_value = mock_gen

        comp = TickerComparator(["AAPL", "MSFT"])
        comp.fetch_all()
        df = comp.key_metrics_table()

        assert "AAPL" in df.columns
        assert "Market Cap" in df.index


# ============================================================
# PortfolioView Tests
# ============================================================


class TestPortfolioView:
    def test_equal_weights_default(self):
        pv = PortfolioView(tickers=["AAPL", "MSFT", "GOOGL"])
        assert len(pv.weights) == 3
        assert abs(sum(pv.weights) - 1.0) < 0.001

    def test_custom_weights(self):
        pv = PortfolioView(tickers=["AAPL", "MSFT"], weights=[0.6, 0.4])
        assert pv.weights == [0.6, 0.4]

    def test_mismatched_weights_raises(self):
        with pytest.raises(ValueError, match="must match"):
            PortfolioView(tickers=["AAPL", "MSFT"], weights=[0.5])

    def test_weights_not_summing_to_one_raises(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            PortfolioView(tickers=["AAPL", "MSFT"], weights=[0.3, 0.3])


# ============================================================
# Helper function tests
# ============================================================


class TestSafeMetric:
    def test_basic_extraction(self):
        assert _safe_metric({"pe": 25.0}, "pe") == 25.0

    def test_missing_key(self):
        assert _safe_metric({}, "pe") is None

    def test_with_multiply(self):
        assert _safe_metric({"growth": 0.15}, "growth", multiply=100) == 15.0

    def test_with_divisor(self):
        result = _safe_metric(
            {"fcf": 50e9}, "fcf",
            divisor_key="mcap", multiply=100,
            source={"mcap": 1e12},
        )
        assert result == 5.0

    def test_divisor_zero(self):
        assert _safe_metric({"a": 10}, "a", divisor_key="b", source={"b": 0}) is None


class TestFormatLargeNumber:
    def test_trillion(self):
        assert _format_large_number(3e12) == "3.0T"

    def test_billion(self):
        assert _format_large_number(1.5e9) == "1.5B"

    def test_million(self):
        assert _format_large_number(250e6) == "250.0M"

    def test_thousand(self):
        assert _format_large_number(5000) == "5.0K"

    def test_none(self):
        assert _format_large_number(None) is None


# ============================================================
# Formatter tests
# ============================================================


class TestFormatters:
    def _sample_df(self):
        return pd.DataFrame({
            "AAPL": {"Score": 72.5, "Signal": "Buy"},
            "MSFT": {"Score": 68.0, "Signal": "Hold"},
        })

    def test_format_table(self):
        output = format_comparison_table(self._sample_df(), title="Test")
        assert "AAPL" in output
        assert "MSFT" in output
        assert "Test" in output

    def test_format_table_empty(self):
        output = format_comparison_table(pd.DataFrame())
        assert "no data" in output

    def test_format_markdown(self):
        output = format_comparison_markdown(self._sample_df(), title="Test")
        assert "| Metric |" in output
        assert "AAPL" in output

    def test_format_markdown_empty(self):
        output = format_comparison_markdown(pd.DataFrame())
        assert "No data" in output

    def test_format_json(self):
        import json

        output = format_comparison_json(scores_df=self._sample_df())
        parsed = json.loads(output)
        assert "scores" in parsed
        assert "AAPL" in parsed["scores"]

    def test_format_correlation_heatmap(self):
        corr = pd.DataFrame(
            {"AAPL": {"AAPL": 1.0, "MSFT": 0.85}, "MSFT": {"AAPL": 0.85, "MSFT": 1.0}}
        )
        output = format_correlation_heatmap(corr)
        assert "CORRELATION MATRIX" in output
        assert "0.850" in output

    def test_format_correlation_heatmap_empty(self):
        output = format_correlation_heatmap(pd.DataFrame())
        assert "no correlation" in output
