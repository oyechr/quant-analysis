"""
Tests for the Composite Scoring Engine
Tests dimension scorers, composite scoring, configuration, and output formatting.
"""

import json
import math
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scoring import (
    FundamentalScorer,
    RiskScorer,
    ScoringConfig,
    StockScorer,
    TechnicalScorer,
    ValuationScorer,
)
from src.scoring.config import DimensionWeight, SignalThresholds
from src.scoring.dimensions import DimensionResult, SubScore, _clamp, _linear_scale, _safe_float


# ============================================================
# Test Fixtures
# ============================================================


def _load_sample_report(ticker: str = "AAPL") -> dict:
    """Load a sample full report JSON for testing"""
    report_path = Path(__file__).parent.parent / "data" / ticker / "reports" / "full_report.json"
    if not report_path.exists():
        pytest.skip(f"Sample report not found: {report_path}")
    with open(report_path) as f:
        return json.load(f)


def _load_analysis_json(ticker: str, analysis_type: str) -> dict:
    """Load a specific analysis JSON file"""
    path = (
        Path(__file__).parent.parent
        / "data"
        / ticker
        / "reports"
        / f"{analysis_type}.json"
    )
    if not path.exists():
        pytest.skip(f"Analysis file not found: {path}")
    with open(path) as f:
        return json.load(f)


# ============================================================
# Test Utility Functions
# ============================================================


class TestUtilityFunctions:
    """Tests for helper functions in dimensions module"""

    def test_safe_float_with_number(self):
        assert _safe_float(42.5) == 42.5

    def test_safe_float_with_int(self):
        assert _safe_float(7) == 7.0

    def test_safe_float_with_none(self):
        assert _safe_float(None) is None

    def test_safe_float_with_none_and_default(self):
        assert _safe_float(None, 50.0) == 50.0

    def test_safe_float_with_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_float_with_inf(self):
        assert _safe_float(float("inf")) is None

    def test_safe_float_with_string(self):
        assert _safe_float("not a number") is None

    def test_safe_float_with_numeric_string(self):
        assert _safe_float("42.5") == 42.5

    def test_clamp_within_range(self):
        assert _clamp(50.0) == 50.0

    def test_clamp_below_range(self):
        assert _clamp(-10.0) == 0.0

    def test_clamp_above_range(self):
        assert _clamp(150.0) == 100.0

    def test_clamp_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0

    def test_linear_scale_midpoint(self):
        result = _linear_scale(50.0, 0.0, 100.0)
        assert result == 50.0

    def test_linear_scale_at_worst(self):
        result = _linear_scale(0.0, 0.0, 100.0)
        assert result == 0.0

    def test_linear_scale_at_best(self):
        result = _linear_scale(100.0, 0.0, 100.0)
        assert result == 100.0

    def test_linear_scale_inverted(self):
        result = _linear_scale(25.0, 0.0, 100.0, invert=True)
        assert result == 75.0

    def test_linear_scale_clamped(self):
        result = _linear_scale(150.0, 0.0, 100.0)
        assert result == 100.0


# ============================================================
# Test Scoring Configuration
# ============================================================


class TestScoringConfig:
    """Tests for ScoringConfig dataclass"""

    def test_default_weights_sum_to_one(self):
        config = ScoringConfig()
        total = (
            config.weights.technical
            + config.weights.fundamental
            + config.weights.risk
            + config.weights.valuation
        )
        assert abs(total - 1.0) < 0.01

    def test_invalid_weights_raises(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            DimensionWeight(technical=0.5, fundamental=0.5, risk=0.5, valuation=0.5)

    def test_signal_thresholds(self):
        config = ScoringConfig()
        assert config.get_signal(90.0) == "Strong Buy"
        assert config.get_signal(70.0) == "Buy"
        assert config.get_signal(55.0) == "Hold"
        assert config.get_signal(40.0) == "Sell"
        assert config.get_signal(20.0) == "Strong Sell"

    def test_signal_boundary_strong_buy(self):
        config = ScoringConfig()
        assert config.get_signal(80.0) == "Strong Buy"

    def test_signal_boundary_buy(self):
        config = ScoringConfig()
        assert config.get_signal(65.0) == "Buy"

    def test_signal_boundary_hold(self):
        config = ScoringConfig()
        assert config.get_signal(50.0) == "Hold"

    def test_signal_boundary_sell(self):
        config = ScoringConfig()
        assert config.get_signal(35.0) == "Sell"

    def test_value_investor_preset(self):
        config = ScoringConfig.value_investor()
        assert config.weights.fundamental > config.weights.technical
        assert config.weights.valuation > config.weights.technical

    def test_growth_investor_preset(self):
        config = ScoringConfig.growth_investor()
        assert config.weights.technical > config.weights.risk

    def test_income_investor_preset(self):
        config = ScoringConfig.income_investor()
        assert config.weights.risk > config.weights.technical

    def test_preset_weights_sum_to_one(self):
        for preset in [
            ScoringConfig.value_investor(),
            ScoringConfig.growth_investor(),
            ScoringConfig.income_investor(),
        ]:
            total = (
                preset.weights.technical
                + preset.weights.fundamental
                + preset.weights.risk
                + preset.weights.valuation
            )
            assert abs(total - 1.0) < 0.01

    def test_save_and_load_config(self, tmp_path):
        config = ScoringConfig.value_investor()
        config_file = tmp_path / "scoring_config.json"
        config.save_to_file(config_file)

        loaded = ScoringConfig.load_from_file(config_file)
        assert loaded.weights.technical == config.weights.technical
        assert loaded.weights.fundamental == config.weights.fundamental

    def test_load_missing_file_returns_default(self, tmp_path):
        config = ScoringConfig.load_from_file(tmp_path / "nonexistent.json")
        assert config.weights.technical == 0.25  # default


# ============================================================
# Test SubScore and DimensionResult
# ============================================================


class TestSubScore:
    """Tests for SubScore dataclass"""

    def test_weighted_score(self):
        s = SubScore(name="Test", score=80.0, weight=0.25)
        assert s.weighted_score() == 20.0

    def test_weighted_score_unavailable(self):
        s = SubScore(name="Test", score=80.0, weight=0.25, available=False)
        assert s.weighted_score() == 0.0


class TestDimensionResult:
    """Tests for DimensionResult dataclass"""

    def test_to_dict_structure(self):
        result = DimensionResult(
            dimension="Technical",
            score=72.5,
            sub_scores=[
                SubScore(name="RSI", score=65.0, weight=0.2, raw_value=45.0, label="Neutral")
            ],
            data_coverage=1.0,
            strengths=["test strength"],
            concerns=["test concern"],
        )
        d = result.to_dict()
        assert d["dimension"] == "Technical"
        assert d["score"] == 72.5
        assert d["data_coverage"] == 1.0
        assert len(d["sub_scores"]) == 1
        assert d["sub_scores"][0]["name"] == "RSI"
        assert d["strengths"] == ["test strength"]
        assert d["concerns"] == ["test concern"]


# ============================================================
# Test Technical Scorer
# ============================================================


class TestTechnicalScorer:
    """Tests for TechnicalScorer"""

    def _make_tech_data(self, **overrides):
        """Build a technical analysis data dict with defaults"""
        indicators = {
            "RSI_14": 50.0,
            "MACD_diff": 1.0,
            "SMA_20": 100.0,
            "SMA_50": 95.0,
            "SMA_200": 90.0,
            "ADX_14": 30.0,
            "MFI_14": 50.0,
            "BB_upper": 110.0,
            "BB_lower": 90.0,
            "BB_middle": 100.0,
            "Williams_R_14": -50.0,
        }
        indicators.update(overrides.get("indicators", {}))
        return {
            "latest_values": {
                "close_price": overrides.get("close_price", 100.0),
                "indicators": indicators,
            },
            "signals": overrides.get("signals", {
                "MACD": "Bullish",
                "MA_Trend": "Bullish (Golden Cross)",
            }),
        }

    def test_score_returns_dimension_result(self):
        scorer = TechnicalScorer()
        result = scorer.score(self._make_tech_data())
        assert isinstance(result, DimensionResult)
        assert result.dimension == "Technical"

    def test_score_is_bounded(self):
        scorer = TechnicalScorer()
        result = scorer.score(self._make_tech_data())
        assert 0 <= result.score <= 100

    def test_data_coverage_with_all_data(self):
        scorer = TechnicalScorer()
        result = scorer.score(self._make_tech_data())
        assert result.data_coverage == 1.0

    def test_rsi_oversold_bullish(self):
        scorer = TechnicalScorer()
        data = self._make_tech_data(indicators={"RSI_14": 20.0})
        result = scorer.score(data)
        rsi_score = next(s for s in result.sub_scores if s.name == "RSI")
        assert rsi_score.score >= 70.0  # Oversold = bullish

    def test_rsi_overbought_bearish(self):
        scorer = TechnicalScorer()
        data = self._make_tech_data(indicators={"RSI_14": 80.0})
        result = scorer.score(data)
        rsi_score = next(s for s in result.sub_scores if s.name == "RSI")
        assert rsi_score.score <= 30.0  # Overbought = bearish

    def test_rsi_neutral(self):
        scorer = TechnicalScorer()
        data = self._make_tech_data(indicators={"RSI_14": 50.0})
        result = scorer.score(data)
        rsi_score = next(s for s in result.sub_scores if s.name == "RSI")
        assert 40.0 <= rsi_score.score <= 70.0

    def test_macd_bullish_high_score(self):
        scorer = TechnicalScorer()
        data = self._make_tech_data(signals={"MACD": "Bullish"})
        result = scorer.score(data)
        macd_score = next(s for s in result.sub_scores if s.name == "MACD")
        assert macd_score.score >= 65.0

    def test_macd_bearish_low_score(self):
        scorer = TechnicalScorer()
        data = self._make_tech_data(signals={"MACD": "Bearish"})
        result = scorer.score(data)
        macd_score = next(s for s in result.sub_scores if s.name == "MACD")
        assert macd_score.score <= 35.0

    def test_golden_cross_boosts_ma_score(self):
        scorer = TechnicalScorer()
        data = self._make_tech_data(signals={"MACD": "Neutral", "MA_Trend": "Bullish (Golden Cross)"})
        result = scorer.score(data)
        ma_score = next(s for s in result.sub_scores if s.name == "MA Alignment")
        assert "Golden Cross" in ma_score.label

    def test_empty_data_returns_neutral(self):
        scorer = TechnicalScorer()
        result = scorer.score({})
        assert result.score == 50.0
        assert result.data_coverage == 0.0

    def test_with_sample_data(self):
        data = _load_analysis_json("AAPL", "technical_analysis")
        scorer = TechnicalScorer()
        result = scorer.score(data)
        assert 0 <= result.score <= 100
        assert result.data_coverage > 0


# ============================================================
# Test Fundamental Scorer
# ============================================================


class TestFundamentalScorer:
    """Tests for FundamentalScorer"""

    def _make_fund_data(self, **overrides):
        """Build fundamental analysis data with defaults"""
        data = {
            "analysis": {
                "quality_scores": {
                    "piotroski_f": overrides.get("f_score", 7),
                    "altman_z": overrides.get("z_score", 5.0),
                },
                "growth_rates": {
                    "revenue": {"1y": overrides.get("rev_growth", 10.0), "3y_cagr": 8.0},
                    "earnings": {"1y": overrides.get("earn_growth", 15.0), "3y_cagr": 10.0},
                },
                "margins": {
                    "current": {
                        "gross_margin": overrides.get("gross_margin", 40.0),
                        "operating_margin": overrides.get("operating_margin", 20.0),
                    }
                },
                "dupont": {"roe_reported": overrides.get("roe", 15.0)},
            }
        }
        return data

    def test_score_returns_dimension_result(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data())
        assert isinstance(result, DimensionResult)
        assert result.dimension == "Fundamental"

    def test_score_is_bounded(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data())
        assert 0 <= result.score <= 100

    def test_strong_f_score_high_result(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(f_score=9))
        f_sub = next(s for s in result.sub_scores if s.name == "Piotroski F-Score")
        assert f_sub.score >= 90.0

    def test_weak_f_score_low_result(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(f_score=2))
        f_sub = next(s for s in result.sub_scores if s.name == "Piotroski F-Score")
        assert f_sub.score <= 30.0

    def test_z_score_safe_zone(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(z_score=4.0))
        z_sub = next(s for s in result.sub_scores if s.name == "Altman Z-Score")
        assert z_sub.score >= 70.0
        assert "Safe" in z_sub.label

    def test_z_score_distress(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(z_score=1.5))
        z_sub = next(s for s in result.sub_scores if s.name == "Altman Z-Score")
        assert z_sub.score <= 40.0
        assert "Distress" in z_sub.label

    def test_strong_growth(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(rev_growth=25.0, earn_growth=30.0))
        rev_sub = next(s for s in result.sub_scores if s.name == "Revenue Growth")
        assert rev_sub.score >= 75.0

    def test_declining_revenue_penalized(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(rev_growth=-10.0))
        rev_sub = next(s for s in result.sub_scores if s.name == "Revenue Growth")
        assert rev_sub.score <= 30.0

    def test_excellent_margins(self):
        scorer = FundamentalScorer()
        result = scorer.score(self._make_fund_data(gross_margin=50.0, operating_margin=25.0))
        prof_sub = next(s for s in result.sub_scores if s.name == "Profitability")
        assert prof_sub.score >= 75.0

    def test_with_sample_data(self):
        data = _load_analysis_json("AAPL", "fundamental_analysis")
        scorer = FundamentalScorer()
        result = scorer.score(data)
        assert 0 <= result.score <= 100
        assert result.data_coverage > 0


# ============================================================
# Test Risk Scorer
# ============================================================


class TestRiskScorer:
    """Tests for RiskScorer"""

    def _make_risk_data(self, **overrides):
        """Build risk analysis data with defaults"""
        return {
            "sharpe_ratio": overrides.get("sharpe", 1.0),
            "sortino_ratio": overrides.get("sortino", 1.5),
            "drawdown": {
                "max_drawdown": overrides.get("max_dd", -0.15),
            },
            "market_risk": {
                "beta": overrides.get("beta", 1.0),
            },
            "volatility": {
                "annualized_volatility": overrides.get("volatility", 0.20),
            },
            "var_95": {
                "var_historical": overrides.get("var_95", -0.025),
            },
        }

    def test_score_returns_dimension_result(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data())
        assert isinstance(result, DimensionResult)
        assert result.dimension == "Risk"

    def test_score_is_bounded(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data())
        assert 0 <= result.score <= 100

    def test_excellent_sharpe(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(sharpe=2.5))
        sharpe_sub = next(s for s in result.sub_scores if s.name == "Sharpe Ratio")
        assert sharpe_sub.score >= 85.0

    def test_negative_sharpe(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(sharpe=-0.5))
        sharpe_sub = next(s for s in result.sub_scores if s.name == "Sharpe Ratio")
        assert sharpe_sub.score <= 30.0

    def test_low_drawdown_good_score(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(max_dd=-0.05))
        dd_sub = next(s for s in result.sub_scores if s.name == "Max Drawdown")
        assert dd_sub.score >= 80.0

    def test_severe_drawdown_bad_score(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(max_dd=-0.45))
        dd_sub = next(s for s in result.sub_scores if s.name == "Max Drawdown")
        assert dd_sub.score <= 35.0

    def test_moderate_beta_good_score(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(beta=1.0))
        beta_sub = next(s for s in result.sub_scores if s.name == "Beta")
        assert beta_sub.score >= 70.0

    def test_high_beta_lower_score(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(beta=2.0))
        beta_sub = next(s for s in result.sub_scores if s.name == "Beta")
        assert beta_sub.score <= 60.0

    def test_low_volatility_high_score(self):
        scorer = RiskScorer()
        result = scorer.score(self._make_risk_data(volatility=0.10))
        vol_sub = next(s for s in result.sub_scores if s.name == "Volatility")
        assert vol_sub.score >= 85.0

    def test_with_sample_data(self):
        data = _load_analysis_json("AAPL", "risk_analysis")
        scorer = RiskScorer()
        result = scorer.score(data)
        assert 0 <= result.score <= 100
        assert result.data_coverage > 0


# ============================================================
# Test Valuation Scorer
# ============================================================


class TestValuationScorer:
    """Tests for ValuationScorer"""

    def _make_val_data(self, **overrides):
        """Build valuation analysis data with defaults"""
        return {
            "dcf_valuation": {
                "discount_premium_pct": overrides.get("dcf_premium", -20.0),
                "error": overrides.get("dcf_error", None),
            },
            "dividend_analysis": {
                "pays_dividends": overrides.get("pays_dividends", True),
                "sustainability_score": overrides.get("div_sustainability", 75.0),
            },
            "earnings_analysis": {
                "earnings_quality": {
                    "score": overrides.get("earnings_quality", 70.0),
                },
                "surprise_stats": {
                    "beat_rate": overrides.get("beat_rate", 75.0),
                },
            },
        }

    def _make_ticker_info(self, **overrides):
        return {
            "pe_ratio": overrides.get("pe", 20.0),
            "peg_ratio": overrides.get("peg", 1.5),
        }

    def test_score_returns_dimension_result(self):
        scorer = ValuationScorer()
        result = scorer.score(self._make_val_data(), self._make_ticker_info())
        assert isinstance(result, DimensionResult)
        assert result.dimension == "Valuation"

    def test_score_is_bounded(self):
        scorer = ValuationScorer()
        result = scorer.score(self._make_val_data(), self._make_ticker_info())
        assert 0 <= result.score <= 100

    def test_deeply_undervalued_dcf(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(dcf_premium=-40.0), self._make_ticker_info()
        )
        dcf_sub = next(s for s in result.sub_scores if s.name == "DCF Valuation")
        assert dcf_sub.score >= 85.0

    def test_overvalued_dcf(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(dcf_premium=100.0), self._make_ticker_info()
        )
        dcf_sub = next(s for s in result.sub_scores if s.name == "DCF Valuation")
        assert dcf_sub.score <= 30.0

    def test_low_pe_attractive(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(), self._make_ticker_info(pe=10.0)
        )
        pe_sub = next(s for s in result.sub_scores if s.name == "P/E Ratio")
        assert pe_sub.score >= 75.0

    def test_high_pe_expensive(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(), self._make_ticker_info(pe=50.0)
        )
        pe_sub = next(s for s in result.sub_scores if s.name == "P/E Ratio")
        assert pe_sub.score <= 30.0

    def test_low_peg_undervalued(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(), self._make_ticker_info(peg=0.8)
        )
        peg_sub = next(s for s in result.sub_scores if s.name == "PEG Ratio")
        assert peg_sub.score >= 80.0

    def test_no_dividend_neutral_score(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(pays_dividends=False), self._make_ticker_info()
        )
        div_sub = next(s for s in result.sub_scores if s.name == "Dividend Sustainability")
        assert div_sub.score == 50.0

    def test_dcf_error_unavailable(self):
        scorer = ValuationScorer()
        result = scorer.score(
            self._make_val_data(dcf_error="No FCF data"), self._make_ticker_info()
        )
        dcf_sub = next(s for s in result.sub_scores if s.name == "DCF Valuation")
        assert not dcf_sub.available

    def test_with_sample_data(self):
        data = _load_analysis_json("AAPL", "valuation_analysis")
        scorer = ValuationScorer()
        info = _load_sample_report("AAPL").get("info", {})
        result = scorer.score(data, info)
        assert 0 <= result.score <= 100


# ============================================================
# Test Composite StockScorer
# ============================================================


class TestStockScorer:
    """Tests for the main StockScorer composite scorer"""

    def test_score_full_report(self):
        report = _load_sample_report("AAPL")
        scorer = StockScorer()
        result = scorer.score(report)
        assert 0 <= result.composite_score <= 100
        assert result.signal in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
        assert result.confidence in ["High", "Medium", "Low"]
        assert result.ticker == "AAPL"

    def test_score_all_sample_tickers(self):
        """Test scoring works for all sample tickers"""
        for ticker in ["AAPL", "EXE.TO", "GJF.OL"]:
            report = _load_sample_report(ticker)
            scorer = StockScorer()
            result = scorer.score(report)
            assert 0 <= result.composite_score <= 100, f"Failed for {ticker}"
            assert result.dimensions_available >= 1, f"No dimensions for {ticker}"

    def test_dimensions_available(self):
        report = _load_sample_report("AAPL")
        scorer = StockScorer()
        result = scorer.score(report)
        assert result.dimensions_available >= 3  # At least tech, fund, risk
        assert result.dimensions_total == 4

    def test_confidence_with_full_data(self):
        report = _load_sample_report("AAPL")
        scorer = StockScorer()
        result = scorer.score(report)
        assert result.confidence_score >= 0.5

    def test_empty_report_neutral(self):
        scorer = StockScorer()
        result = scorer.score({"ticker": "TEST"})
        assert result.composite_score == 50.0
        assert result.confidence == "Low"
        assert result.dimensions_available == 0

    def test_partial_data_still_scores(self):
        """Test that scorer works with only some dimensions available"""
        report = _load_sample_report("AAPL")
        # Remove some data
        report.pop("risk_analysis", None)
        report.pop("valuation_analysis", None)
        scorer = StockScorer()
        result = scorer.score(report)
        assert 0 <= result.composite_score <= 100
        assert result.risk is None
        assert result.valuation is None
        assert result.technical is not None

    def test_score_from_analyses(self):
        """Test scoring from individual analysis files"""
        tech = _load_analysis_json("AAPL", "technical_analysis")
        fund = _load_analysis_json("AAPL", "fundamental_analysis")
        risk = _load_analysis_json("AAPL", "risk_analysis")
        val = _load_analysis_json("AAPL", "valuation_analysis")
        info = _load_sample_report("AAPL").get("info", {})

        scorer = StockScorer()
        result = scorer.score_from_analyses(
            technical_data=tech,
            fundamental_data=fund,
            risk_data=risk,
            valuation_data=val,
            ticker_info=info,
            ticker="AAPL",
        )
        assert 0 <= result.composite_score <= 100
        assert result.ticker == "AAPL"

    def test_different_configs_produce_different_scores(self):
        report = _load_sample_report("AAPL")

        default_scorer = StockScorer()
        value_scorer = StockScorer(ScoringConfig.value_investor())
        growth_scorer = StockScorer(ScoringConfig.growth_investor())

        default_result = default_scorer.score(report)
        value_result = value_scorer.score(report)
        growth_result = growth_scorer.score(report)

        # Different weights should produce different composite scores
        scores = {
            default_result.composite_score,
            value_result.composite_score,
            growth_result.composite_score,
        }
        # At least 2 distinct scores (could be same if dimension scores are identical)
        assert len(scores) >= 2


# ============================================================
# Test Output Formatting
# ============================================================


class TestOutputFormatting:
    """Tests for scoring result output formats"""

    def _get_result(self) -> "ScoringResult":
        report = _load_sample_report("AAPL")
        scorer = StockScorer()
        return scorer.score(report)

    def test_to_dict_structure(self):
        result = self._get_result()
        d = result.to_dict()
        assert "ticker" in d
        assert "composite_score" in d
        assert "signal" in d
        assert "confidence" in d
        assert "dimensions" in d
        assert "strengths" in d
        assert "concerns" in d
        assert "metadata" in d

    def test_to_dict_is_json_serializable(self):
        result = self._get_result()
        d = result.to_dict()
        # Should not raise
        json_str = json.dumps(d, default=str)
        assert len(json_str) > 0

    def test_format_scorecard(self):
        result = self._get_result()
        scorecard = result.format_scorecard()
        assert "STOCK SCORE: AAPL" in scorecard
        assert "Composite Score:" in scorecard
        assert "Confidence:" in scorecard
        assert "DIMENSION BREAKDOWN" in scorecard
        assert "Technical" in scorecard
        assert "Fundamental" in scorecard

    def test_format_for_toon(self):
        result = self._get_result()
        toon = result.format_for_toon()
        assert "composite_score" in toon
        assert "signal" in toon
        assert "confidence" in toon
        assert "dimension_scores" in toon

    def test_format_llm_context(self):
        result = self._get_result()
        llm = result.format_llm_context()
        assert "QUANTITATIVE ASSESSMENT:" in llm
        assert "Overall Score:" in llm
        assert "Confidence:" in llm

    def test_scorecard_includes_strengths(self):
        result = self._get_result()
        if result.strengths:
            scorecard = result.format_scorecard()
            assert "STRENGTHS" in scorecard

    def test_scorecard_includes_concerns(self):
        result = self._get_result()
        if result.concerns:
            scorecard = result.format_scorecard()
            assert "CONCERNS" in scorecard

    def test_score_bar_format(self):
        from src.scoring.scorer import ScoringResult

        bar = ScoringResult._score_bar(50.0, width=10)
        assert "█" in bar
        assert "░" in bar
        assert len(bar) == 12  # 10 chars + 2 brackets


# ============================================================
# Test Edge Cases
# ============================================================


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_none_values_in_technical(self):
        scorer = TechnicalScorer()
        data = {
            "latest_values": {
                "close_price": None,
                "indicators": {
                    "RSI_14": None,
                    "MACD_diff": None,
                    "SMA_20": None,
                    "SMA_50": None,
                    "SMA_200": None,
                    "ADX_14": None,
                    "MFI_14": None,
                    "BB_upper": None,
                    "BB_lower": None,
                    "Williams_R_14": None,
                },
            },
            "signals": {},
        }
        result = scorer.score(data)
        assert result.score == 50.0
        assert result.data_coverage == 0.0

    def test_nan_values_in_risk(self):
        scorer = RiskScorer()
        data = {
            "sharpe_ratio": float("nan"),
            "sortino_ratio": float("nan"),
            "drawdown": {"max_drawdown": float("nan")},
            "market_risk": {"beta": float("nan")},
            "volatility": {"annualized_volatility": float("nan")},
            "var_95": {"var_historical": float("nan")},
        }
        result = scorer.score(data)
        assert result.score == 50.0

    def test_extreme_values(self):
        """Test scorer handles extreme but valid values"""
        scorer = RiskScorer()
        data = {
            "sharpe_ratio": 10.0,
            "sortino_ratio": 15.0,
            "drawdown": {"max_drawdown": -0.90},
            "market_risk": {"beta": 5.0},
            "volatility": {"annualized_volatility": 1.5},
            "var_95": {"var_historical": -0.20},
        }
        result = scorer.score(data)
        assert 0 <= result.score <= 100

    def test_negative_pe_handled(self):
        scorer = ValuationScorer()
        data = {
            "dcf_valuation": {"discount_premium_pct": None, "error": "No data"},
            "dividend_analysis": {"pays_dividends": False},
            "earnings_analysis": {},
        }
        info = {"pe_ratio": -5.0, "peg_ratio": -1.0}
        result = scorer.score(data, info)
        pe_sub = next(s for s in result.sub_scores if s.name == "P/E Ratio")
        assert not pe_sub.available  # Negative P/E should be marked unavailable

    def test_missing_nested_keys(self):
        """Test scorer handles missing nested dictionary keys gracefully"""
        scorer = FundamentalScorer()
        data = {"analysis": {}}
        result = scorer.score(data)
        assert 0 <= result.score <= 100
