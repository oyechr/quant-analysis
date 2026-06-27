"""
Tests for new quant methods: Factor Ranking, Relative Strength, PEAD, Risk Parity, Correlation Flags.
Focused on logic correctness with minimal redundancy.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.fundamental import calculate_pead_signal
from src.analysis.technical import calculate_relative_strength
from src.comparison.comparator import calculate_risk_parity_weights, identify_correlation_flags
from src.discovery.factor_ranking import FactorRanker, FactorScore, FactorWeights
from src.utils.financial import calculate_kelly_criterion


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def sample_price_data():
    """Generate 252 days of synthetic price data"""
    np.random.seed(42)
    dates = pd.date_range("2025-06-27", periods=252, freq="B")
    returns = np.random.normal(0.0005, 0.02, 252)
    prices = 100.0 * np.cumprod(1 + returns)
    return pd.DataFrame({"Close": prices, "Volume": 1000000}, index=dates)


@pytest.fixture
def sample_benchmark():
    """Benchmark (less volatile)"""
    np.random.seed(99)
    dates = pd.date_range("2025-06-27", periods=252, freq="B")
    returns = np.random.normal(0.0003, 0.01, 252)
    prices = 100.0 * np.cumprod(1 + returns)
    return pd.DataFrame({"Close": prices, "Volume": 5000000}, index=dates)


@pytest.fixture
def sample_earnings():
    """Realistic earnings history"""
    return [
        {"quarter": "2026-03-31", "epsActual": 1.52, "epsEstimate": 1.40, "epsDifference": 0.12, "surprisePercent": 0.0857},
        {"quarter": "2025-12-31", "epsActual": 1.45, "epsEstimate": 1.38, "epsDifference": 0.07, "surprisePercent": 0.0507},
        {"quarter": "2025-09-30", "epsActual": 1.30, "epsEstimate": 1.35, "epsDifference": -0.05, "surprisePercent": -0.037},
        {"quarter": "2025-06-30", "epsActual": 1.25, "epsEstimate": 1.20, "epsDifference": 0.05, "surprisePercent": 0.0417},
    ]


# ============================================================
# Test Relative Strength
# ============================================================


class TestRelativeStrength:
    def test_returns_none_for_short_data(self):
        short = pd.DataFrame({"Close": [100, 101, 102]}, index=pd.date_range("2026-01-01", periods=3))
        assert calculate_relative_strength(short) is None

    def test_returns_valid_rating(self, sample_price_data, sample_benchmark):
        rs = calculate_relative_strength(sample_price_data, sample_benchmark)
        assert rs is not None
        assert 1 <= rs["rs_rating"] <= 99
        assert "interpretation" in rs
        assert "weighted_return_pct" in rs

    def test_rating_without_benchmark(self, sample_price_data):
        rs = calculate_relative_strength(sample_price_data)
        assert rs is not None
        assert 1 <= rs["rs_rating"] <= 99

    def test_components_present(self, sample_price_data, sample_benchmark):
        rs = calculate_relative_strength(sample_price_data, sample_benchmark)
        components = rs["components"]
        assert "return_3mo" in components


# ============================================================
# Test PEAD Signal
# ============================================================


class TestPEAD:
    def test_returns_none_for_insufficient_data(self):
        assert calculate_pead_signal([]) is None
        assert calculate_pead_signal([{"epsActual": 1.0, "epsEstimate": 0.9, "epsDifference": 0.1}]) is None

    def test_calculates_sue(self, sample_earnings):
        result = calculate_pead_signal(sample_earnings)
        assert result is not None
        assert result["sue"] is not None
        assert isinstance(result["sue"], float)

    def test_positive_surprise_signal(self, sample_earnings):
        result = calculate_pead_signal(sample_earnings)
        # Latest beat by 0.12 with std ~0.08 → SUE > 1
        assert result["signal"] in ("buy", "strong_buy", "slight_positive")

    def test_negative_surprise_signal(self):
        earnings = [
            {"quarter": "2026-03-31", "epsActual": 0.80, "epsEstimate": 1.10, "epsDifference": -0.30, "surprisePercent": -0.27},
            {"quarter": "2025-12-31", "epsActual": 0.90, "epsEstimate": 1.05, "epsDifference": -0.15, "surprisePercent": -0.14},
            {"quarter": "2025-09-30", "epsActual": 0.95, "epsEstimate": 1.00, "epsDifference": -0.05, "surprisePercent": -0.05},
        ]
        result = calculate_pead_signal(earnings)
        assert result is not None
        assert result["signal"] in ("sell", "strong_sell", "slight_negative")

    def test_streak_detection(self, sample_earnings):
        result = calculate_pead_signal(sample_earnings)
        # First two are beats, third is miss — streak should be 2
        assert result["streak"] == 2
        assert result["streak_direction"] == "beat"

    def test_drift_confirmation_with_price_data(self, sample_earnings, sample_price_data):
        result = calculate_pead_signal(sample_earnings, sample_price_data)
        # drift_confirmed should be set (True or False)
        assert "drift_confirmed" in result


# ============================================================
# Test Factor Ranking
# ============================================================


class TestFactorRanking:
    def test_needs_at_least_two_tickers(self):
        ranker = FactorRanker()
        result = ranker.rank_universe({"ONLY": {"info": {}, "price_data": pd.DataFrame()}})
        assert result == []

    def test_ranks_two_tickers(self, sample_price_data, sample_benchmark):
        ranker = FactorRanker()
        ticker_data = {
            "HIGH_VOL": {
                "info": {"pe_ratio": 15, "price_to_book": 2.0, "roe": 0.15, "debtToEquity": 0.5},
                "price_data": sample_price_data,
                "report": {},
            },
            "LOW_VOL": {
                "info": {"pe_ratio": 25, "price_to_book": 4.0, "roe": 0.10, "debtToEquity": 1.5},
                "price_data": sample_benchmark,  # Lower vol
                "report": {},
            },
        }
        results = ranker.rank_universe(ticker_data)
        assert len(results) == 2
        # Both should have composite scores
        assert all(r.composite_score is not None for r in results)
        # LOW_VOL should rank higher on low_vol factor
        low_vol_result = next(r for r in results if r.ticker == "LOW_VOL")
        high_vol_result = next(r for r in results if r.ticker == "HIGH_VOL")
        assert low_vol_result.low_vol_score > high_vol_result.low_vol_score

    def test_value_factor_cheaper_scores_higher(self):
        ranker = FactorRanker()
        cheap = ranker._calc_value_factor({"info": {"pe_ratio": 10, "price_to_book": 1.0}})
        expensive = ranker._calc_value_factor({"info": {"pe_ratio": 50, "price_to_book": 5.0}})
        assert cheap > expensive

    def test_custom_weights(self, sample_price_data, sample_benchmark):
        weights = FactorWeights(value=0.0, quality=0.0, momentum=1.0, low_volatility=0.0)
        ranker = FactorRanker(weights=weights)
        ticker_data = {
            "A": {"info": {}, "price_data": sample_price_data, "report": {}},
            "B": {"info": {}, "price_data": sample_benchmark, "report": {}},
        }
        results = ranker.rank_universe(ticker_data)
        assert len(results) == 2

    def test_format_rankings(self, sample_price_data, sample_benchmark):
        ranker = FactorRanker()
        ticker_data = {
            "TICK_A": {"info": {"pe_ratio": 15}, "price_data": sample_price_data, "report": {}},
            "TICK_B": {"info": {"pe_ratio": 25}, "price_data": sample_benchmark, "report": {}},
        }
        results = ranker.rank_universe(ticker_data)
        output = ranker.format_rankings(results)
        assert "TICK_A" in output
        assert "TICK_B" in output


# ============================================================
# Test Risk Parity
# ============================================================


class TestRiskParity:
    def test_returns_none_for_single_ticker(self, sample_price_data):
        result = calculate_risk_parity_weights({"ONLY": sample_price_data})
        assert result is None

    def test_weights_sum_to_one(self, sample_price_data, sample_benchmark):
        result = calculate_risk_parity_weights({"A": sample_price_data, "B": sample_benchmark})
        assert result is not None
        total = sum(result["weights"].values())
        assert abs(total - 1.0) < 0.001

    def test_lower_vol_gets_higher_weight(self, sample_price_data, sample_benchmark):
        # sample_benchmark has lower vol (std=0.01 vs 0.02)
        result = calculate_risk_parity_weights({"HIGH": sample_price_data, "LOW": sample_benchmark})
        assert result["weights"]["LOW"] > result["weights"]["HIGH"]

    def test_returns_volatilities(self, sample_price_data, sample_benchmark):
        result = calculate_risk_parity_weights({"A": sample_price_data, "B": sample_benchmark})
        assert "volatilities" in result
        assert result["volatilities"]["A"] > result["volatilities"]["B"]


# ============================================================
# Test Correlation Flags
# ============================================================


class TestCorrelationFlags:
    def test_empty_matrix(self):
        assert identify_correlation_flags(pd.DataFrame()) == {}

    def test_detects_redundant_pair(self):
        # Perfect correlation
        corr = pd.DataFrame(
            [[1.0, 0.95], [0.95, 1.0]],
            columns=["A", "B"], index=["A", "B"]
        )
        flags = identify_correlation_flags(corr)
        assert len(flags["redundant_pairs"]) == 1
        assert flags["redundant_pairs"][0]["correlation"] == 0.95

    def test_detects_hedge_opportunity(self):
        corr = pd.DataFrame(
            [[1.0, -0.5], [-0.5, 1.0]],
            columns=["A", "B"], index=["A", "B"]
        )
        flags = identify_correlation_flags(corr)
        assert len(flags["hedge_opportunities"]) == 1

    def test_diversification_score_range(self):
        corr = pd.DataFrame(
            [[1.0, 0.3], [0.3, 1.0]],
            columns=["A", "B"], index=["A", "B"]
        )
        flags = identify_correlation_flags(corr)
        assert 0 <= flags["diversification_score"] <= 100

    def test_high_correlation_low_diversification(self):
        corr = pd.DataFrame(
            [[1.0, 0.9], [0.9, 1.0]],
            columns=["A", "B"], index=["A", "B"]
        )
        flags = identify_correlation_flags(corr)
        assert flags["diversification_score"] < 30


# ============================================================
# Test Kelly Criterion
# ============================================================


class TestKellyCriterion:
    def test_returns_none_for_short_data(self):
        short = pd.DataFrame({"Close": [100, 101, 102]}, index=pd.date_range("2026-01-01", periods=3))
        assert calculate_kelly_criterion(short) is None

    def test_returns_valid_result(self, sample_price_data):
        result = calculate_kelly_criterion(sample_price_data)
        assert result is not None
        assert "kelly_pct" in result
        assert "half_kelly_pct" in result
        assert "win_rate" in result
        assert 0 <= result["win_rate"] <= 1

    def test_half_kelly_is_half(self, sample_price_data):
        result = calculate_kelly_criterion(sample_price_data)
        assert abs(result["half_kelly_pct"] - result["kelly_pct"] / 2) < 0.001
