"""
Dimension Scorers
Individual scoring functions for each analysis dimension (Technical, Fundamental, Risk, Valuation).
Each scorer normalizes metrics to a 0-100 scale and tracks data coverage for confidence.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import ScoringConfig

logger = logging.getLogger(__name__)


@dataclass
class SubScore:
    """Individual metric score with metadata"""

    name: str
    score: float  # 0-100
    weight: float  # Relative weight within dimension
    raw_value: Optional[float] = None
    label: str = ""
    available: bool = True

    def weighted_score(self) -> float:
        """Return the weight-adjusted score"""
        return self.score * self.weight if self.available else 0.0


@dataclass
class DimensionResult:
    """Result of scoring a single dimension"""

    dimension: str
    score: float  # 0-100 (weighted average of sub-scores)
    sub_scores: List[SubScore] = field(default_factory=list)
    data_coverage: float = 0.0  # 0-1, fraction of metrics with available data
    strengths: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary"""
        return {
            "dimension": self.dimension,
            "score": round(self.score, 1),
            "data_coverage": round(self.data_coverage, 2),
            "strengths": self.strengths,
            "concerns": self.concerns,
            "sub_scores": [
                {
                    "name": s.name,
                    "score": round(s.score, 1),
                    "weight": round(s.weight, 2),
                    "raw_value": (
                        round(s.raw_value, 4)
                        if s.raw_value is not None and isinstance(s.raw_value, float)
                        else s.raw_value
                    ),
                    "label": s.label,
                    "available": s.available,
                }
                for s in self.sub_scores
            ],
        }


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely convert a value to float, returning default if not possible"""
    if value is None:
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp a value between low and high"""
    return max(low, min(high, value))


def _linear_scale(
    value: float, worst: float, best: float, invert: bool = False
) -> float:
    """
    Linearly scale a value to 0-100.

    Args:
        value: The raw metric value
        worst: The value that maps to 0
        best: The value that maps to 100
        invert: If True, lower values are better (e.g. drawdown)

    Returns:
        Score between 0 and 100
    """
    if abs(best - worst) < 1e-10:
        return 50.0
    score = ((value - worst) / (best - worst)) * 100.0
    if invert:
        score = 100.0 - score
    return _clamp(score)


class TechnicalScorer:
    """Scores technical analysis data on a 0-100 scale"""

    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self.params = self.config.technical

    def score(self, technical_data: Dict[str, Any]) -> DimensionResult:
        """
        Score technical analysis data.

        Args:
            technical_data: Output from TechnicalAnalyzer.get_summary() or
                           the technical_analysis section of a full report

        Returns:
            DimensionResult with technical dimension score
        """
        sub_scores: List[SubScore] = []
        strengths: List[str] = []
        concerns: List[str] = []

        # Extract latest indicator values
        latest = technical_data.get("latest_values", {})
        indicators = latest.get("indicators", {})
        signals = technical_data.get("signals", {})

        # 1. RSI Score (weight: 0.20)
        rsi = _safe_float(indicators.get("RSI_14"))
        sub_scores.append(self._score_rsi(rsi, strengths, concerns))

        # 2. MACD Score (weight: 0.20)
        macd_diff = _safe_float(indicators.get("MACD_diff"))
        macd_signal_str = signals.get("MACD", "")
        sub_scores.append(self._score_macd(macd_diff, macd_signal_str, strengths, concerns))

        # 3. Moving Average Alignment (weight: 0.25)
        close = _safe_float(latest.get("close_price") or indicators.get("close_price"))
        sma_20 = _safe_float(indicators.get("SMA_20"))
        sma_50 = _safe_float(indicators.get("SMA_50"))
        sma_200 = _safe_float(indicators.get("SMA_200"))
        ma_signal = signals.get("MA_Trend", "")
        sub_scores.append(
            self._score_ma_alignment(close, sma_20, sma_50, sma_200, ma_signal, strengths, concerns)
        )

        # 4. ADX Trend Strength (weight: 0.10)
        adx = _safe_float(indicators.get("ADX_14"))
        sub_scores.append(self._score_adx(adx, strengths, concerns))

        # 5. MFI Score (weight: 0.10)
        mfi = _safe_float(indicators.get("MFI_14"))
        sub_scores.append(self._score_mfi(mfi, strengths, concerns))

        # 6. Bollinger Band Position (weight: 0.10)
        bb_upper = _safe_float(indicators.get("BB_upper"))
        bb_lower = _safe_float(indicators.get("BB_lower"))
        bb_middle = _safe_float(indicators.get("BB_middle"))
        sub_scores.append(
            self._score_bollinger(close, bb_upper, bb_lower, bb_middle, strengths, concerns)
        )

        # 7. Williams %R (weight: 0.05)
        williams_r = _safe_float(indicators.get("Williams_R_14"))
        sub_scores.append(self._score_williams_r(williams_r, strengths, concerns))

        return self._build_result("Technical", sub_scores, strengths, concerns)

    def _score_rsi(
        self, rsi: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if rsi is None:
            return SubScore(name="RSI", score=50.0, weight=0.20, available=False)

        # RSI scoring: oversold (high score), neutral (moderate), overbought (low score)
        if rsi <= self.params.rsi_oversold:
            score = _linear_scale(rsi, 0, self.params.rsi_oversold, invert=True)
            score = 70.0 + (score * 0.30)  # 70-100 range for oversold
            label = "Oversold (bullish)"
            strengths.append(f"RSI oversold at {rsi:.1f} — potential buying opportunity")
        elif rsi >= self.params.rsi_overbought:
            score = _linear_scale(rsi, self.params.rsi_overbought, 100, invert=False)
            score = 30.0 - (score * 0.30)  # 0-30 range for overbought
            label = "Overbought (bearish)"
            concerns.append(f"RSI overbought at {rsi:.1f} — potential reversal risk")
        else:
            # Neutral zone: score peaks at 50 RSI
            distance_from_center = abs(rsi - 50.0)
            score = 65.0 - (distance_from_center * 0.5)
            label = "Neutral"

        return SubScore(name="RSI", score=_clamp(score), weight=0.20, raw_value=rsi, label=label)

    def _score_macd(
        self,
        macd_diff: Optional[float],
        signal_str: str,
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if macd_diff is None:
            return SubScore(name="MACD", score=50.0, weight=0.20, available=False)

        is_bullish = "Bullish" in signal_str
        is_bearish = "Bearish" in signal_str

        if is_bullish:
            score = 65.0 + min(abs(macd_diff) * 2, 35.0)
            label = "Bullish crossover"
            strengths.append("MACD bullish crossover — positive momentum")
        elif is_bearish:
            score = 35.0 - min(abs(macd_diff) * 2, 35.0)
            label = "Bearish crossover"
            concerns.append("MACD bearish crossover — negative momentum")
        else:
            # Neutral: slight positive bias if MACD_diff > 0
            score = 50.0 + (min(max(macd_diff, -10), 10) * 1.5)
            label = "Neutral"

        return SubScore(
            name="MACD", score=_clamp(score), weight=0.20, raw_value=macd_diff, label=label
        )

    def _score_ma_alignment(
        self,
        close: Optional[float],
        sma_20: Optional[float],
        sma_50: Optional[float],
        sma_200: Optional[float],
        signal_str: str,
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if close is None or sma_200 is None:
            return SubScore(name="MA Alignment", score=50.0, weight=0.25, available=False)

        score = 50.0
        bullish_count = 0
        bearish_count = 0

        # Price vs each MA
        if sma_20 is not None:
            if close > sma_20:
                bullish_count += 1
            else:
                bearish_count += 1

        if sma_50 is not None:
            if close > sma_50:
                bullish_count += 1
            else:
                bearish_count += 1

        if close > sma_200:
            bullish_count += 1
        else:
            bearish_count += 1

        # MA ordering (golden/death cross)
        if sma_50 is not None:
            if sma_50 > sma_200:
                bullish_count += 1
            else:
                bearish_count += 1

        total = bullish_count + bearish_count
        if total > 0:
            score = (bullish_count / total) * 100.0

        # Boost for golden/death cross
        if "Golden Cross" in signal_str:
            score = min(score + 10.0, 100.0)
            label = "Bullish (Golden Cross)"
            strengths.append("Golden Cross — SMA 50 above SMA 200")
        elif "Death Cross" in signal_str:
            score = max(score - 10.0, 0.0)
            label = "Bearish (Death Cross)"
            concerns.append("Death Cross — SMA 50 below SMA 200")
        elif score >= 70:
            label = "Bullish alignment"
            strengths.append("Price above key moving averages")
        elif score <= 30:
            label = "Bearish alignment"
            concerns.append("Price below key moving averages")
        else:
            label = "Mixed signals"

        return SubScore(
            name="MA Alignment", score=_clamp(score), weight=0.25, raw_value=close, label=label
        )

    def _score_adx(
        self, adx: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if adx is None:
            return SubScore(name="ADX", score=50.0, weight=0.10, available=False)

        # ADX measures trend strength (not direction). Strong trend = higher score
        if adx >= self.params.adx_very_strong:
            score = 85.0
            label = "Very strong trend"
            strengths.append(f"ADX {adx:.1f} — very strong trend")
        elif adx >= self.params.adx_strong_trend:
            score = 70.0
            label = "Strong trend"
        else:
            # Weak trend: 20-60 range
            score = 20.0 + (adx / self.params.adx_strong_trend) * 40.0
            label = "Weak/no trend"

        return SubScore(name="ADX", score=_clamp(score), weight=0.10, raw_value=adx, label=label)

    def _score_mfi(
        self, mfi: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if mfi is None:
            return SubScore(name="MFI", score=50.0, weight=0.10, available=False)

        if mfi <= self.params.mfi_oversold:
            score = 80.0
            label = "Oversold (bullish)"
            strengths.append(f"MFI oversold at {mfi:.1f} — money flow suggests buying pressure")
        elif mfi >= self.params.mfi_overbought:
            score = 20.0
            label = "Overbought (bearish)"
            concerns.append(f"MFI overbought at {mfi:.1f} — heavy selling pressure possible")
        else:
            # Linear scale in neutral zone
            score = _linear_scale(mfi, self.params.mfi_overbought, self.params.mfi_oversold)
            label = "Neutral"

        return SubScore(name="MFI", score=_clamp(score), weight=0.10, raw_value=mfi, label=label)

    def _score_bollinger(
        self,
        close: Optional[float],
        bb_upper: Optional[float],
        bb_lower: Optional[float],
        bb_middle: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if close is None or bb_upper is None or bb_lower is None:
            return SubScore(
                name="Bollinger Bands", score=50.0, weight=0.10, available=False
            )

        bb_width = bb_upper - bb_lower
        if bb_width < 1e-10:
            return SubScore(
                name="Bollinger Bands", score=50.0, weight=0.10, raw_value=close, label="Flat"
            )

        # Position within bands (0 = lower, 1 = upper)
        position = (close - bb_lower) / bb_width

        if position >= 1.0:
            score = 25.0  # Above upper band = overextended
            label = "Above upper band"
            concerns.append("Price above Bollinger upper band — overextended")
        elif position <= 0.0:
            score = 75.0  # Below lower band = oversold bounce potential
            label = "Below lower band"
            strengths.append("Price below Bollinger lower band — potential bounce")
        elif position > 0.8:
            score = 35.0
            label = "Near upper band"
        elif position < 0.2:
            score = 65.0
            label = "Near lower band"
        else:
            score = 50.0
            label = "Mid-range"

        return SubScore(
            name="Bollinger Bands",
            score=_clamp(score),
            weight=0.10,
            raw_value=round(position, 3),
            label=label,
        )

    def _score_williams_r(
        self, williams_r: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if williams_r is None:
            return SubScore(name="Williams %R", score=50.0, weight=0.05, available=False)

        # Williams %R ranges from -100 (oversold) to 0 (overbought)
        if williams_r <= -80:
            score = 80.0
            label = "Oversold"
        elif williams_r >= -20:
            score = 20.0
            label = "Overbought"
            concerns.append(f"Williams %R at {williams_r:.1f} — overbought zone")
        else:
            # Linear scale: -80 (80 score) to -20 (20 score)
            score = _linear_scale(williams_r, -20, -80)
            label = "Neutral"

        return SubScore(
            name="Williams %R",
            score=_clamp(score),
            weight=0.05,
            raw_value=williams_r,
            label=label,
        )

    def _build_result(
        self,
        dimension: str,
        sub_scores: List[SubScore],
        strengths: List[str],
        concerns: List[str],
    ) -> DimensionResult:
        """Build dimension result from sub-scores with proper weight normalization"""
        available = [s for s in sub_scores if s.available]
        total_available_weight = sum(s.weight for s in available)

        if total_available_weight > 0:
            # Re-normalize weights so available metrics sum to 1.0
            score = sum(s.score * (s.weight / total_available_weight) for s in available)
        else:
            score = 50.0  # Default neutral if no data

        data_coverage = len(available) / len(sub_scores) if sub_scores else 0.0

        return DimensionResult(
            dimension=dimension,
            score=_clamp(score),
            sub_scores=sub_scores,
            data_coverage=data_coverage,
            strengths=strengths,
            concerns=concerns,
        )


class FundamentalScorer:
    """Scores fundamental analysis data on a 0-100 scale"""

    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self.params = self.config.fundamental

    def score(
        self,
        fundamental_data: Dict[str, Any],
        ticker_info: Optional[Dict[str, Any]] = None,
    ) -> DimensionResult:
        """
        Score fundamental analysis data.

        Args:
            fundamental_data: Output from FundamentalAnalyzer.get_summary() or
                             the fundamental_analysis section of a full report
            ticker_info: Optional ticker info dict for additional metrics (ROE, ROA, etc.)

        Returns:
            DimensionResult with fundamental dimension score
        """
        sub_scores: List[SubScore] = []
        strengths: List[str] = []
        concerns: List[str] = []

        # Extract analysis data
        analysis = fundamental_data.get("analysis", fundamental_data)

        # 1. Piotroski F-Score (weight: 0.25)
        quality = analysis.get("quality_scores", {})
        f_score = _safe_float(quality.get("piotroski_f"))
        sub_scores.append(self._score_piotroski(f_score, strengths, concerns))

        # 2. Altman Z-Score (weight: 0.20)
        z_score = _safe_float(quality.get("altman_z"))
        sub_scores.append(self._score_altman_z(z_score, strengths, concerns))

        # 3. Revenue Growth (weight: 0.15)
        growth = analysis.get("growth_rates", {})
        revenue_growth = growth.get("revenue", {})
        rev_1y = _safe_float(revenue_growth.get("1y"))
        rev_3y = _safe_float(revenue_growth.get("3y_cagr"))
        sub_scores.append(self._score_revenue_growth(rev_1y, rev_3y, strengths, concerns))

        # 4. Earnings Growth (weight: 0.15)
        earnings_growth = growth.get("earnings", {})
        earn_1y = _safe_float(earnings_growth.get("1y"))
        earn_3y = _safe_float(earnings_growth.get("3y_cagr"))
        sub_scores.append(self._score_earnings_growth(earn_1y, earn_3y, strengths, concerns))

        # 5. Profitability / Margins (weight: 0.15)
        margins = analysis.get("margins", {}).get("current", {})
        gross_margin = _safe_float(margins.get("gross_margin"))
        operating_margin = _safe_float(margins.get("operating_margin"))
        sub_scores.append(
            self._score_profitability(gross_margin, operating_margin, strengths, concerns)
        )

        # 6. Return on Equity (weight: 0.10)
        roe = None
        if ticker_info:
            roe = _safe_float(ticker_info.get("roe"))
        if roe is None:
            dupont = analysis.get("dupont", {})
            roe = _safe_float(dupont.get("roe_reported") or dupont.get("roe_calculated"))
        sub_scores.append(self._score_roe(roe, strengths, concerns))

        return self._build_result("Fundamental", sub_scores, strengths, concerns)

    def _score_piotroski(
        self, f_score: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if f_score is None:
            return SubScore(name="Piotroski F-Score", score=50.0, weight=0.25, available=False)

        f_score_int = int(f_score)
        # F-Score 0-9 → normalize to 0-100
        score = (f_score_int / 9.0) * 100.0

        if f_score_int >= self.params.f_score_strong:
            label = "Strong"
            strengths.append(f"Piotroski F-Score {f_score_int}/9 — strong fundamentals")
        elif f_score_int >= self.params.f_score_average:
            label = "Average"
        else:
            label = "Weak"
            concerns.append(f"Piotroski F-Score {f_score_int}/9 — weak fundamentals")

        return SubScore(
            name="Piotroski F-Score",
            score=_clamp(score),
            weight=0.25,
            raw_value=float(f_score_int),
            label=label,
        )

    def _score_altman_z(
        self, z_score: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if z_score is None:
            return SubScore(name="Altman Z-Score", score=50.0, weight=0.20, available=False)

        if z_score > self.params.z_score_safe:
            # Safe zone: score 70-100 based on how far above threshold
            score = 70.0 + min((z_score - self.params.z_score_safe) * 5, 30.0)
            label = "Safe zone"
            strengths.append(f"Altman Z-Score {z_score:.2f} — safe zone (low bankruptcy risk)")
        elif z_score > self.params.z_score_grey:
            # Grey zone: 40-70
            range_size = self.params.z_score_safe - self.params.z_score_grey
            score = 40.0 + ((z_score - self.params.z_score_grey) / range_size) * 30.0
            label = "Grey zone"
        else:
            # Distress zone: 0-40
            score = max(z_score / self.params.z_score_grey * 40.0, 0.0)
            label = "Distress zone"
            concerns.append(f"Altman Z-Score {z_score:.2f} — financial distress risk")

        return SubScore(
            name="Altman Z-Score",
            score=_clamp(score),
            weight=0.20,
            raw_value=z_score,
            label=label,
        )

    def _score_revenue_growth(
        self,
        growth_1y: Optional[float],
        growth_3y: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        # Use 1Y if available, fall back to 3Y CAGR
        growth = growth_1y if growth_1y is not None else growth_3y
        if growth is None:
            return SubScore(name="Revenue Growth", score=50.0, weight=0.15, available=False)

        if growth >= self.params.revenue_growth_strong:
            score = 75.0 + min((growth - self.params.revenue_growth_strong) * 0.5, 25.0)
            label = "Strong growth"
            strengths.append(f"Revenue growth {growth:.1f}% — strong")
        elif growth >= self.params.revenue_growth_moderate:
            score = 50.0 + (
                (growth - self.params.revenue_growth_moderate)
                / (self.params.revenue_growth_strong - self.params.revenue_growth_moderate)
            ) * 25.0
            label = "Moderate growth"
        elif growth >= 0:
            score = 30.0 + (growth / self.params.revenue_growth_moderate) * 20.0
            label = "Slow growth"
        else:
            score = max(30.0 + growth, 0.0)  # Negative growth penalized
            label = "Declining"
            concerns.append(f"Revenue declining at {growth:.1f}%")

        return SubScore(
            name="Revenue Growth",
            score=_clamp(score),
            weight=0.15,
            raw_value=growth,
            label=label,
        )

    def _score_earnings_growth(
        self,
        growth_1y: Optional[float],
        growth_3y: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        growth = growth_1y if growth_1y is not None else growth_3y
        if growth is None:
            return SubScore(name="Earnings Growth", score=50.0, weight=0.15, available=False)

        if growth >= self.params.earnings_growth_strong:
            score = 75.0 + min((growth - self.params.earnings_growth_strong) * 0.4, 25.0)
            label = "Strong growth"
            strengths.append(f"Earnings growth {growth:.1f}% — strong")
        elif growth >= self.params.earnings_growth_moderate:
            score = 50.0 + (
                (growth - self.params.earnings_growth_moderate)
                / (self.params.earnings_growth_strong - self.params.earnings_growth_moderate)
            ) * 25.0
            label = "Moderate growth"
        elif growth >= 0:
            score = 30.0 + (growth / self.params.earnings_growth_moderate) * 20.0
            label = "Slow growth"
        else:
            score = max(30.0 + growth * 0.5, 0.0)
            label = "Declining"
            concerns.append(f"Earnings declining at {growth:.1f}%")

        return SubScore(
            name="Earnings Growth",
            score=_clamp(score),
            weight=0.15,
            raw_value=growth,
            label=label,
        )

    def _score_profitability(
        self,
        gross_margin: Optional[float],
        operating_margin: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if gross_margin is None and operating_margin is None:
            return SubScore(name="Profitability", score=50.0, weight=0.15, available=False)

        scores = []
        if gross_margin is not None:
            if gross_margin >= self.params.gross_margin_excellent:
                scores.append(85.0)
            elif gross_margin >= self.params.gross_margin_good:
                scores.append(60.0)
            elif gross_margin >= 0:
                scores.append(35.0)
            else:
                scores.append(10.0)

        if operating_margin is not None:
            if operating_margin >= self.params.operating_margin_excellent:
                scores.append(85.0)
            elif operating_margin >= self.params.operating_margin_good:
                scores.append(60.0)
            elif operating_margin >= 0:
                scores.append(35.0)
            else:
                scores.append(10.0)

        score = sum(scores) / len(scores)

        if score >= 75:
            label = "Excellent margins"
            strengths.append(
                f"Strong profitability — gross {gross_margin:.1f}%, "
                f"operating {operating_margin:.1f}%"
                if gross_margin and operating_margin
                else "Strong profitability margins"
            )
        elif score >= 50:
            label = "Good margins"
        elif score >= 25:
            label = "Thin margins"
        else:
            label = "Unprofitable"
            concerns.append("Low or negative profit margins")

        raw = gross_margin if gross_margin is not None else operating_margin

        return SubScore(
            name="Profitability",
            score=_clamp(score),
            weight=0.15,
            raw_value=raw,
            label=label,
        )

    def _score_roe(
        self, roe: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if roe is None:
            return SubScore(name="ROE", score=50.0, weight=0.10, available=False)

        # ROE as percentage (some APIs return as decimal, some as %)
        roe_pct = roe * 100.0 if abs(roe) < 1.0 else roe

        if roe_pct >= self.params.roe_excellent:
            score = 80.0 + min((roe_pct - self.params.roe_excellent) * 0.3, 20.0)
            label = "Excellent"
            strengths.append(f"ROE {roe_pct:.1f}% — excellent return on equity")
        elif roe_pct >= self.params.roe_good:
            score = 55.0 + (
                (roe_pct - self.params.roe_good)
                / (self.params.roe_excellent - self.params.roe_good)
            ) * 25.0
            label = "Good"
        elif roe_pct >= 0:
            score = 25.0 + (roe_pct / self.params.roe_good) * 30.0
            label = "Low"
        else:
            score = max(25.0 + roe_pct, 0.0)
            label = "Negative"
            concerns.append(f"Negative ROE ({roe_pct:.1f}%) — company losing money on equity")

        return SubScore(
            name="ROE", score=_clamp(score), weight=0.10, raw_value=roe_pct, label=label
        )

    def _build_result(
        self,
        dimension: str,
        sub_scores: List[SubScore],
        strengths: List[str],
        concerns: List[str],
    ) -> DimensionResult:
        available = [s for s in sub_scores if s.available]
        total_available_weight = sum(s.weight for s in available)

        if total_available_weight > 0:
            score = sum(s.score * (s.weight / total_available_weight) for s in available)
        else:
            score = 50.0

        data_coverage = len(available) / len(sub_scores) if sub_scores else 0.0

        return DimensionResult(
            dimension=dimension,
            score=_clamp(score),
            sub_scores=sub_scores,
            data_coverage=data_coverage,
            strengths=strengths,
            concerns=concerns,
        )


class RiskScorer:
    """Scores risk analysis data on a 0-100 scale (higher = lower risk = better)"""

    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self.params = self.config.risk

    def score(self, risk_data: Dict[str, Any]) -> DimensionResult:
        """
        Score risk analysis data.

        Args:
            risk_data: Output from RiskMetrics.calculate_all_metrics() or
                      the risk_analysis section of a full report

        Returns:
            DimensionResult with risk dimension score (higher = lower risk = better)
        """
        sub_scores: List[SubScore] = []
        strengths: List[str] = []
        concerns: List[str] = []

        # 1. Sharpe Ratio (weight: 0.25)
        sharpe = _safe_float(risk_data.get("sharpe_ratio"))
        sub_scores.append(self._score_sharpe(sharpe, strengths, concerns))

        # 2. Sortino Ratio (weight: 0.15)
        sortino = _safe_float(risk_data.get("sortino_ratio"))
        sub_scores.append(self._score_sortino(sortino, strengths, concerns))

        # 3. Maximum Drawdown (weight: 0.25)
        drawdown = risk_data.get("drawdown", {})
        max_dd = _safe_float(drawdown.get("max_drawdown"))
        sub_scores.append(self._score_drawdown(max_dd, strengths, concerns))

        # 4. Beta (weight: 0.15)
        market_risk = risk_data.get("market_risk", {})
        beta = _safe_float(market_risk.get("beta"))
        sub_scores.append(self._score_beta(beta, strengths, concerns))

        # 5. Volatility (weight: 0.15)
        vol_data = risk_data.get("volatility", {})
        ann_vol = _safe_float(vol_data.get("annualized_volatility"))
        sub_scores.append(self._score_volatility(ann_vol, strengths, concerns))

        # 6. VaR (weight: 0.05)
        var_data = risk_data.get("var_95", {})
        var_95 = _safe_float(var_data.get("var_historical"))
        sub_scores.append(self._score_var(var_95, strengths, concerns))

        return self._build_result("Risk", sub_scores, strengths, concerns)

    def _score_sharpe(
        self, sharpe: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if sharpe is None:
            return SubScore(name="Sharpe Ratio", score=50.0, weight=0.25, available=False)

        if sharpe >= self.params.sharpe_excellent:
            score = 90.0
            label = "Excellent"
            strengths.append(f"Sharpe ratio {sharpe:.2f} — excellent risk-adjusted returns")
        elif sharpe >= self.params.sharpe_good:
            score = 70.0 + (
                (sharpe - self.params.sharpe_good)
                / (self.params.sharpe_excellent - self.params.sharpe_good)
            ) * 20.0
            label = "Good"
            strengths.append(f"Sharpe ratio {sharpe:.2f} — good risk-adjusted returns")
        elif sharpe >= self.params.sharpe_acceptable:
            score = 50.0 + (
                (sharpe - self.params.sharpe_acceptable)
                / (self.params.sharpe_good - self.params.sharpe_acceptable)
            ) * 20.0
            label = "Acceptable"
        elif sharpe >= 0:
            score = 25.0 + (sharpe / self.params.sharpe_acceptable) * 25.0
            label = "Poor"
            concerns.append(f"Sharpe ratio {sharpe:.2f} — poor risk-adjusted returns")
        else:
            score = max(25.0 + sharpe * 10, 0.0)
            label = "Negative"
            concerns.append(f"Negative Sharpe ratio ({sharpe:.2f}) — underperforming risk-free rate")

        return SubScore(
            name="Sharpe Ratio", score=_clamp(score), weight=0.25, raw_value=sharpe, label=label
        )

    def _score_sortino(
        self, sortino: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if sortino is None:
            return SubScore(name="Sortino Ratio", score=50.0, weight=0.15, available=False)

        # Similar logic to Sharpe but typically higher values
        if sortino >= 3.0:
            score = 90.0
            label = "Excellent"
        elif sortino >= 1.5:
            score = 70.0 + ((sortino - 1.5) / 1.5) * 20.0
            label = "Good"
        elif sortino >= 0.5:
            score = 45.0 + ((sortino - 0.5) / 1.0) * 25.0
            label = "Acceptable"
        elif sortino >= 0:
            score = 20.0 + (sortino / 0.5) * 25.0
            label = "Poor"
        else:
            score = max(20.0 + sortino * 5, 0.0)
            label = "Negative"

        return SubScore(
            name="Sortino Ratio", score=_clamp(score), weight=0.15, raw_value=sortino, label=label
        )

    def _score_drawdown(
        self, max_dd: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if max_dd is None:
            return SubScore(name="Max Drawdown", score=50.0, weight=0.25, available=False)

        # max_dd is typically negative, work with absolute value
        dd_abs = abs(max_dd)

        if dd_abs <= self.params.drawdown_low:
            score = 90.0
            label = "Low risk"
            strengths.append(f"Max drawdown only {dd_abs:.1%} — low downside risk")
        elif dd_abs <= self.params.drawdown_moderate:
            score = 65.0 + (
                (self.params.drawdown_moderate - dd_abs)
                / (self.params.drawdown_moderate - self.params.drawdown_low)
            ) * 25.0
            label = "Moderate"
        elif dd_abs <= self.params.drawdown_high:
            score = 35.0 + (
                (self.params.drawdown_high - dd_abs)
                / (self.params.drawdown_high - self.params.drawdown_moderate)
            ) * 30.0
            label = "High risk"
            concerns.append(f"Max drawdown {dd_abs:.1%} — significant downside risk")
        else:
            score = max(35.0 - (dd_abs - self.params.drawdown_high) * 50, 0.0)
            label = "Very high risk"
            concerns.append(f"Max drawdown {dd_abs:.1%} — severe drawdown risk")

        return SubScore(
            name="Max Drawdown",
            score=_clamp(score),
            weight=0.25,
            raw_value=max_dd,
            label=label,
        )

    def _score_beta(
        self, beta: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if beta is None:
            return SubScore(name="Beta", score=50.0, weight=0.15, available=False)

        # Ideal beta: 0.7-1.3 (moderate market sensitivity)
        if self.params.beta_ideal_low <= beta <= self.params.beta_ideal_high:
            score = 75.0
            label = "Moderate"
        elif beta < self.params.beta_ideal_low:
            # Low beta = defensive, generally good but may underperform
            if beta >= 0:
                score = 65.0 + (beta / self.params.beta_ideal_low) * 10.0
                label = "Defensive"
                strengths.append(f"Beta {beta:.2f} — defensive, low market sensitivity")
            else:
                score = 50.0  # Negative beta is unusual
                label = "Negative (unusual)"
        else:
            # High beta = aggressive, higher risk
            excess = beta - self.params.beta_ideal_high
            score = max(75.0 - excess * 25, 15.0)
            label = "Aggressive"
            if beta > 1.8:
                concerns.append(f"Beta {beta:.2f} — highly volatile relative to market")

        return SubScore(
            name="Beta", score=_clamp(score), weight=0.15, raw_value=beta, label=label
        )

    def _score_volatility(
        self, ann_vol: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if ann_vol is None:
            return SubScore(name="Volatility", score=50.0, weight=0.15, available=False)

        if ann_vol <= self.params.volatility_low:
            score = 90.0
            label = "Low"
            strengths.append(f"Annualized volatility {ann_vol:.1%} — low")
        elif ann_vol <= self.params.volatility_moderate:
            score = 60.0 + (
                (self.params.volatility_moderate - ann_vol)
                / (self.params.volatility_moderate - self.params.volatility_low)
            ) * 30.0
            label = "Moderate"
        elif ann_vol <= self.params.volatility_high:
            score = 25.0 + (
                (self.params.volatility_high - ann_vol)
                / (self.params.volatility_high - self.params.volatility_moderate)
            ) * 35.0
            label = "High"
            concerns.append(f"Annualized volatility {ann_vol:.1%} — elevated risk")
        else:
            score = max(25.0 - (ann_vol - self.params.volatility_high) * 30, 0.0)
            label = "Very high"
            concerns.append(f"Annualized volatility {ann_vol:.1%} — very high risk")

        return SubScore(
            name="Volatility",
            score=_clamp(score),
            weight=0.15,
            raw_value=ann_vol,
            label=label,
        )

    def _score_var(
        self, var_95: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if var_95 is None:
            return SubScore(name="VaR (95%)", score=50.0, weight=0.05, available=False)

        # VaR is typically negative (worst expected daily loss)
        var_abs = abs(var_95)

        if var_abs <= 0.02:
            score = 85.0
            label = "Low daily risk"
        elif var_abs <= 0.03:
            score = 65.0
            label = "Moderate daily risk"
        elif var_abs <= 0.05:
            score = 40.0
            label = "Elevated daily risk"
        else:
            score = 20.0
            label = "High daily risk"

        return SubScore(
            name="VaR (95%)",
            score=_clamp(score),
            weight=0.05,
            raw_value=var_95,
            label=label,
        )

    def _build_result(
        self,
        dimension: str,
        sub_scores: List[SubScore],
        strengths: List[str],
        concerns: List[str],
    ) -> DimensionResult:
        available = [s for s in sub_scores if s.available]
        total_available_weight = sum(s.weight for s in available)

        if total_available_weight > 0:
            score = sum(s.score * (s.weight / total_available_weight) for s in available)
        else:
            score = 50.0

        data_coverage = len(available) / len(sub_scores) if sub_scores else 0.0

        return DimensionResult(
            dimension=dimension,
            score=_clamp(score),
            sub_scores=sub_scores,
            data_coverage=data_coverage,
            strengths=strengths,
            concerns=concerns,
        )


class ValuationScorer:
    """Scores valuation analysis data on a 0-100 scale (higher = more undervalued = better)"""

    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self.params = self.config.valuation

    def score(
        self,
        valuation_data: Dict[str, Any],
        ticker_info: Optional[Dict[str, Any]] = None,
    ) -> DimensionResult:
        """
        Score valuation analysis data.

        Args:
            valuation_data: Output from ValuationAnalyzer.analyze() or
                           the valuation_analysis section of a full report
            ticker_info: Optional ticker info dict for P/E, P/B, PEG, etc.

        Returns:
            DimensionResult with valuation dimension score
        """
        sub_scores: List[SubScore] = []
        strengths: List[str] = []
        concerns: List[str] = []

        # 1. DCF Valuation (weight: 0.25)
        dcf = valuation_data.get("dcf_valuation", {})
        dcf_premium = _safe_float(dcf.get("discount_premium_pct"))
        dcf_error = dcf.get("error")
        sub_scores.append(self._score_dcf(dcf_premium, dcf_error, strengths, concerns))

        # 2. P/E Ratio (weight: 0.20)
        pe = None
        if ticker_info:
            pe = _safe_float(ticker_info.get("pe_ratio"))
        sub_scores.append(self._score_pe(pe, strengths, concerns))

        # 3. PEG Ratio (weight: 0.15)
        peg = None
        if ticker_info:
            peg = _safe_float(ticker_info.get("peg_ratio"))
        sub_scores.append(self._score_peg(peg, strengths, concerns))

        # 4. FCF Yield (weight: 0.15)
        # Try to get from fundamental data embedded in valuation or directly
        fcf_yield = None
        if "fcf_metrics" in valuation_data:
            fcf_yield = _safe_float(valuation_data["fcf_metrics"].get("fcf_yield"))
        sub_scores.append(self._score_fcf_yield(fcf_yield, strengths, concerns))

        # 5. Dividend Sustainability (weight: 0.10)
        div_analysis = valuation_data.get("dividend_analysis", {})
        div_sustainability = _safe_float(div_analysis.get("sustainability_score"))
        pays_dividends = div_analysis.get("pays_dividends", False)
        sub_scores.append(
            self._score_dividend_sustainability(
                div_sustainability, pays_dividends, strengths, concerns
            )
        )

        # 6. Earnings Quality (weight: 0.15)
        earnings = valuation_data.get("earnings_analysis", {})
        earnings_quality_score = _safe_float(
            (earnings.get("earnings_quality") or {}).get("score")
        )
        beat_rate = _safe_float(
            (earnings.get("surprise_stats") or {}).get("beat_rate")
        )
        sub_scores.append(
            self._score_earnings_quality(earnings_quality_score, beat_rate, strengths, concerns)
        )

        return self._build_result("Valuation", sub_scores, strengths, concerns)

    def _score_dcf(
        self,
        premium_pct: Optional[float],
        error: Optional[str],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if premium_pct is None or error:
            return SubScore(name="DCF Valuation", score=50.0, weight=0.25, available=False)

        # premium_pct: positive = overvalued (price > intrinsic), negative = undervalued
        # Invert: lower premium = higher score
        if premium_pct <= self.params.dcf_deep_discount:
            score = 90.0
            label = "Deeply undervalued"
            strengths.append(
                f"DCF shows {abs(premium_pct):.0f}% discount to intrinsic value — deeply undervalued"
            )
        elif premium_pct <= self.params.dcf_moderate_discount:
            score = 70.0 + (
                (self.params.dcf_moderate_discount - premium_pct)
                / (self.params.dcf_moderate_discount - self.params.dcf_deep_discount)
            ) * 20.0
            label = "Undervalued"
            strengths.append(f"DCF shows {abs(premium_pct):.0f}% discount — undervalued")
        elif premium_pct <= self.params.dcf_fair_value_range:
            score = 50.0 + (
                (self.params.dcf_fair_value_range - premium_pct)
                / (self.params.dcf_fair_value_range - self.params.dcf_moderate_discount)
            ) * 20.0
            label = "Near fair value"
        else:
            # Overvalued
            excess = premium_pct - self.params.dcf_fair_value_range
            score = max(50.0 - excess * 0.3, 5.0)
            label = "Overvalued"
            if premium_pct > 50:
                concerns.append(f"DCF shows {premium_pct:.0f}% premium — significantly overvalued")

        return SubScore(
            name="DCF Valuation",
            score=_clamp(score),
            weight=0.25,
            raw_value=premium_pct,
            label=label,
        )

    def _score_pe(
        self, pe: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if pe is None or pe <= 0:
            return SubScore(name="P/E Ratio", score=50.0, weight=0.20, available=False)

        if pe <= self.params.pe_undervalued:
            score = 80.0 + min((self.params.pe_undervalued - pe) * 1.5, 20.0)
            label = "Attractive"
            strengths.append(f"P/E {pe:.1f} — attractively valued")
        elif pe <= self.params.pe_fair:
            score = 50.0 + (
                (self.params.pe_fair - pe)
                / (self.params.pe_fair - self.params.pe_undervalued)
            ) * 30.0
            label = "Fair"
        elif pe <= self.params.pe_expensive:
            score = 25.0 + (
                (self.params.pe_expensive - pe)
                / (self.params.pe_expensive - self.params.pe_fair)
            ) * 25.0
            label = "Expensive"
        else:
            score = max(25.0 - (pe - self.params.pe_expensive) * 0.3, 5.0)
            label = "Very expensive"
            concerns.append(f"P/E {pe:.1f} — richly valued")

        return SubScore(
            name="P/E Ratio", score=_clamp(score), weight=0.20, raw_value=pe, label=label
        )

    def _score_peg(
        self, peg: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if peg is None or peg <= 0:
            return SubScore(name="PEG Ratio", score=50.0, weight=0.15, available=False)

        if peg <= self.params.peg_undervalued:
            score = 85.0
            label = "Undervalued for growth"
            strengths.append(f"PEG {peg:.2f} — undervalued relative to growth rate")
        elif peg <= self.params.peg_fair:
            score = 50.0 + ((self.params.peg_fair - peg) / (self.params.peg_fair - self.params.peg_undervalued)) * 35.0
            label = "Fair"
        else:
            score = max(50.0 - (peg - self.params.peg_fair) * 10, 10.0)
            label = "Expensive for growth"

        return SubScore(
            name="PEG Ratio", score=_clamp(score), weight=0.15, raw_value=peg, label=label
        )

    def _score_fcf_yield(
        self, fcf_yield: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if fcf_yield is None:
            return SubScore(name="FCF Yield", score=50.0, weight=0.15, available=False)

        if fcf_yield >= self.params.fcf_yield_attractive:
            score = 80.0 + min((fcf_yield - self.params.fcf_yield_attractive) * 2, 20.0)
            label = "Attractive"
            strengths.append(f"FCF yield {fcf_yield:.1f}% — strong cash generation")
        elif fcf_yield >= self.params.fcf_yield_moderate:
            score = 50.0 + (
                (fcf_yield - self.params.fcf_yield_moderate)
                / (self.params.fcf_yield_attractive - self.params.fcf_yield_moderate)
            ) * 30.0
            label = "Moderate"
        elif fcf_yield >= 0:
            score = 25.0 + (fcf_yield / self.params.fcf_yield_moderate) * 25.0
            label = "Low"
        else:
            score = 10.0
            label = "Negative (cash burn)"
            concerns.append("Negative FCF yield — company burning cash")

        return SubScore(
            name="FCF Yield",
            score=_clamp(score),
            weight=0.15,
            raw_value=fcf_yield,
            label=label,
        )

    def _score_dividend_sustainability(
        self,
        sustainability_score: Optional[float],
        pays_dividends: bool,
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if not pays_dividends:
            # Non-dividend stocks get neutral score (not penalized)
            return SubScore(
                name="Dividend Sustainability",
                score=50.0,
                weight=0.10,
                label="No dividend",
                available=True,  # Available but neutral
            )

        if sustainability_score is None:
            return SubScore(
                name="Dividend Sustainability", score=50.0, weight=0.10, available=False
            )

        # Direct mapping: sustainability score is already 0-100
        score = sustainability_score

        if score >= self.params.div_sustainability_excellent:
            label = "Excellent"
            strengths.append(f"Dividend sustainability {score:.0f}/100 — highly sustainable")
        elif score >= self.params.div_sustainability_good:
            label = "Good"
        else:
            label = "At risk"
            concerns.append(f"Dividend sustainability {score:.0f}/100 — may be at risk")

        return SubScore(
            name="Dividend Sustainability",
            score=_clamp(score),
            weight=0.10,
            raw_value=sustainability_score,
            label=label,
        )

    def _score_earnings_quality(
        self,
        quality_score: Optional[float],
        beat_rate: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        scores = []
        raw_value = None

        if quality_score is not None:
            scores.append(quality_score)  # Already 0-100
            raw_value = quality_score

        if beat_rate is not None:
            if beat_rate >= self.params.earnings_beat_rate_strong:
                scores.append(80.0)
            elif beat_rate >= self.params.earnings_beat_rate_moderate:
                scores.append(55.0)
            else:
                scores.append(30.0)
            if raw_value is None:
                raw_value = beat_rate

        if not scores:
            return SubScore(name="Earnings Quality", score=50.0, weight=0.15, available=False)

        score = sum(scores) / len(scores)

        if score >= 70:
            label = "High quality"
            strengths.append("High earnings quality with consistent beats")
        elif score >= 45:
            label = "Moderate quality"
        else:
            label = "Low quality"
            concerns.append("Low earnings quality — cash flow doesn't support reported earnings")

        return SubScore(
            name="Earnings Quality",
            score=_clamp(score),
            weight=0.15,
            raw_value=raw_value,
            label=label,
        )

    def _build_result(
        self,
        dimension: str,
        sub_scores: List[SubScore],
        strengths: List[str],
        concerns: List[str],
    ) -> DimensionResult:
        available = [s for s in sub_scores if s.available]
        total_available_weight = sum(s.weight for s in available)

        if total_available_weight > 0:
            score = sum(s.score * (s.weight / total_available_weight) for s in available)
        else:
            score = 50.0

        data_coverage = len(available) / len(sub_scores) if sub_scores else 0.0

        return DimensionResult(
            dimension=dimension,
            score=_clamp(score),
            sub_scores=sub_scores,
            data_coverage=data_coverage,
            strengths=strengths,
            concerns=concerns,
        )
