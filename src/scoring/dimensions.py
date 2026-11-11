"""
Dimension Scorers
Individual scoring functions for each analysis dimension (Technical, Fundamental, Risk, Valuation).
Each scorer normalizes metrics to a 0-100 scale and tracks data coverage for confidence.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..analysis.fundamental import altman_zones
from ..utils.financial import finite_float
from .config import ScoringConfig

logger = logging.getLogger(__name__)

# Sub-score points for a cross on the last bar (the state itself is scored
# continuously; see TechnicalScorer._score_macd and _score_ma_alignment)
MACD_CROSS_BONUS = 10.0
MA_CROSS_BONUS = 10.0

# Where the sub-score curves end (see _piecewise). Inside the configured
# thresholds (ScoringConfig) the score is interpolated; these are the outer
# points, and the thresholds that aren't configurable.
MARGIN_FLOOR = -20.0  # gross or operating margin (%) that scores the minimum, 10
FCF_YIELD_FLOOR = -5.0  # FCF yield (%) that scores the minimum, 10
# Beneish M-Score: above LIKELY a likely manipulator (Beneish 1999), below
# UNLIKELY not; the grey zone between is the ramp from 80 down to 15
BENEISH_LIKELY = -1.78
BENEISH_UNLIKELY = -2.22
# Sortino ratio: acceptable, good, excellent
SORTINO_ACCEPTABLE = 0.5
SORTINO_GOOD = 1.5
SORTINO_EXCELLENT = 3.0
# Daily 95% VaR (absolute): low, moderate, elevated, high
VAR_LOW = 0.02
VAR_MODERATE = 0.03
VAR_ELEVATED = 0.05
VAR_HIGH = 0.07
# An oscillator (0-100) between its bands: 65 at the middle, 0.5 a point less
# per point away (RSI and MFI; Williams %R shifted by 100)
OSCILLATOR_NEUTRAL = [(0.0, 40.0), (50.0, 65.0), (100.0, 40.0)]
BETA_CONCERN = 1.8  # above: "highly volatile relative to market"
DCF_CONCERN_PREMIUM = 50.0  # % over intrinsic value: "significantly overvalued"


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


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp a value between low and high"""
    return max(low, min(high, value))


FINANCIAL_SECTORS = ("financial services", "financial")


def is_financial(ticker_info: Optional[Dict[str, Any]]) -> bool:
    """
    Banks and insurers. Their operating cash flow is mostly deposits, loans
    and float moving through, so cash-flow-based measures (FCF DCF, OCF vs
    earnings, accruals) and the industrial models built on them (Altman Z,
    Beneish M) say little about them; they're judged on earnings, returns,
    P/E, P/B and dividends instead.
    """
    sector = str((ticker_info or {}).get("sector") or "").lower()
    return sector in FINANCIAL_SECTORS


QUALITY_MODELS = ("piotroski_f", "altman_z", "beneish_m", "accruals_quality")
# Fewer Beneish inputs and the M-Score is mostly defaults
BENEISH_MIN_COMPONENTS = 5


def applicable_quality_models(ticker_info: Optional[Dict[str, Any]]) -> Tuple[str, ...]:
    """
    The quality models that apply to a company, the one rule for both the
    scorer and the red flags:

    - banks and insurers: Piotroski only (see `is_financial`);
    - utilities: no Altman Z. Altman's samples left them out, and regulated
      utilities run on heavy debt and negative working capital without
      being distressed;
    - everyone else: all of `QUALITY_MODELS`.
    """
    if is_financial(ticker_info):
        return ("piotroski_f",)
    if str((ticker_info or {}).get("sector") or "").lower() == "utilities":
        return tuple(m for m in QUALITY_MODELS if m != "altman_z")
    return QUALITY_MODELS


def beneish_is_partial(beneish: Optional[Dict[str, Any]]) -> bool:
    """An M-Score from fewer than `BENEISH_MIN_COMPONENTS` of its 8 inputs: a weak signal."""
    components = (beneish or {}).get("components_available")
    return components is not None and components < BENEISH_MIN_COMPONENTS


def _piecewise(x: float, points: Sequence[Tuple[float, float]]) -> float:
    """
    A score from a curve: linear between (x, score) points sorted by x, and
    flat beyond the first and last. Continuous, so a metric crossing a
    threshold moves the score a little, not by a whole band.
    """
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0) if x1 > x0 else y1
    return points[-1][1]


def _build_result(
    dimension: str,
    sub_scores: List[SubScore],
    strengths: List[str],
    concerns: List[str],
) -> DimensionResult:
    """A dimension's score: the weighted average of its available sub-scores
    (weights renormalized over them), or a neutral 50 with none."""
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
        state = technical_data.get("state") or {}
        close = finite_float(latest.get("close_price") or indicators.get("close_price"))

        # 1. RSI Score (weight: 0.20)
        rsi = finite_float(indicators.get("RSI"))
        sub_scores.append(self._score_rsi(rsi, strengths, concerns))

        # 2. MACD Score (weight: 0.20)
        macd_diff = finite_float(indicators.get("MACD_diff"))
        sub_scores.append(
            self._score_macd(macd_diff, state.get("macd_cross"), close, strengths, concerns)
        )

        # 3. Moving Average Alignment (weight: 0.25)
        sma_20 = finite_float(indicators.get("SMA_20"))
        sma_50 = finite_float(indicators.get("SMA_50"))
        sma_200 = finite_float(indicators.get("SMA_200"))
        sub_scores.append(
            self._score_ma_alignment(
                close, sma_20, sma_50, sma_200, state.get("ma_cross"), strengths, concerns
            )
        )

        # 4. ADX Trend Strength (weight: 0.10)
        adx = finite_float(indicators.get("ADX"))
        sub_scores.append(self._score_adx(adx, strengths, concerns))

        # 5. MFI Score (weight: 0.10)
        mfi = finite_float(indicators.get("MFI"))
        sub_scores.append(self._score_mfi(mfi, strengths, concerns))

        # 6. Bollinger Band Position (weight: 0.10)
        bb_upper = finite_float(indicators.get("BB_upper"))
        bb_lower = finite_float(indicators.get("BB_lower"))
        bb_middle = finite_float(indicators.get("BB_middle"))
        sub_scores.append(
            self._score_bollinger(close, bb_upper, bb_lower, bb_middle, strengths, concerns)
        )

        # 7. Williams %R (weight: 0.05)
        williams_r = finite_float(indicators.get("Williams_R"))
        sub_scores.append(self._score_williams_r(williams_r, strengths, concerns))

        return _build_result("Technical", sub_scores, strengths, concerns)

    def _score_rsi(
        self, rsi: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if rsi is None:
            return SubScore(name="RSI", score=50.0, weight=0.20, available=False)

        # RSI scoring: oversold (high score), neutral (moderate), overbought (low score)
        if rsi <= self.params.rsi_oversold:
            score = _piecewise(rsi, [(0.0, 100.0), (self.params.rsi_oversold, 70.0)])
            label = "Oversold (bullish)"
            strengths.append(f"RSI oversold at {rsi:.1f}  -  potential buying opportunity")
        elif rsi >= self.params.rsi_overbought:
            score = _piecewise(rsi, [(self.params.rsi_overbought, 30.0), (100.0, 0.0)])
            label = "Overbought (bearish)"
            concerns.append(f"RSI overbought at {rsi:.1f}  -  potential reversal risk")
        else:
            # Neutral zone: score peaks at 50 RSI
            score = _piecewise(rsi, OSCILLATOR_NEUTRAL)
            label = "Neutral"

        return SubScore(name="RSI", score=_clamp(score), weight=0.20, raw_value=rsi, label=label)

    def _score_macd(
        self,
        macd_diff: Optional[float],
        cross: Optional[str],
        close: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        """
        Continuous in the histogram (MACD minus signal, as % of price), so the
        score doesn't jump where the histogram crosses zero. A cross adds
        `MACD_CROSS_BONUS` on the bar it happens only (`state.macd_cross`).
        """
        if macd_diff is None:
            return SubScore(name="MACD", score=50.0, weight=0.20, available=False)

        # Normalize histogram by close price to make it price-level independent.
        # A diff of 1% of price is a meaningful signal regardless of stock price.
        if close and close > 0:
            macd_diff_pct = (macd_diff / close) * 100.0
        else:
            macd_diff_pct = macd_diff  # fallback if close unavailable

        score = _piecewise(macd_diff_pct, [(-1.75, 15.0), (1.75, 85.0)])
        if cross == "bullish":
            score += MACD_CROSS_BONUS
            label = "Bullish crossover"
            strengths.append("MACD crossed above its signal line  -  momentum turning up")
        elif cross == "bearish":
            score -= MACD_CROSS_BONUS
            label = "Bearish crossover"
            concerns.append("MACD crossed below its signal line  -  momentum turning down")
        elif macd_diff_pct > 0:
            label = "Above signal line"
        elif macd_diff_pct < 0:
            label = "Below signal line"
        else:
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
        cross: Optional[str],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        """
        The share of bullish orderings: price above SMA 20, 50 and 200, and
        SMA 50 above SMA 200 (the regime, counted once). A golden or death
        cross adds `MA_CROSS_BONUS` on the bar it happens only (`state.ma_cross`).
        """
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

        if cross == "golden":
            score = min(score + MA_CROSS_BONUS, 100.0)
            label = "Golden Cross"
            strengths.append("Golden Cross  -  SMA 50 crossed above SMA 200")
        elif cross == "death":
            score = max(score - MA_CROSS_BONUS, 0.0)
            label = "Death Cross"
            concerns.append("Death Cross  -  SMA 50 crossed below SMA 200")
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
        score = _piecewise(
            adx,
            [
                (0.0, 20.0),
                (self.params.adx_strong_trend, 60.0),
                (self.params.adx_very_strong, 85.0),
            ],
        )
        if adx >= self.params.adx_very_strong:
            label = "Very strong trend"
            strengths.append(f"ADX {adx:.1f}  -  very strong trend")
        elif adx >= self.params.adx_strong_trend:
            label = "Strong trend"
        else:
            label = "Moderate trend" if adx >= self.params.adx_moderate_trend else "Weak/no trend"

        return SubScore(name="ADX", score=_clamp(score), weight=0.10, raw_value=adx, label=label)

    def _score_mfi(
        self, mfi: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if mfi is None:
            return SubScore(name="MFI", score=50.0, weight=0.10, available=False)

        # Same shape as RSI, so the score never jumps up when MFI crosses into a band
        if mfi <= self.params.mfi_oversold:
            score = _piecewise(mfi, [(0.0, 100.0), (self.params.mfi_oversold, 70.0)])
            label = "Oversold (bullish)"
            strengths.append(f"MFI oversold at {mfi:.1f}  -  money flow suggests buying pressure")
        elif mfi >= self.params.mfi_overbought:
            score = _piecewise(mfi, [(self.params.mfi_overbought, 30.0), (100.0, 0.0)])
            label = "Overbought (bearish)"
            concerns.append(f"MFI overbought at {mfi:.1f}  -  heavy selling pressure possible")
        else:
            # Neutral zone: score peaks at 50 MFI
            score = _piecewise(mfi, OSCILLATOR_NEUTRAL)
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
            return SubScore(name="Bollinger Bands", score=50.0, weight=0.10, available=False)

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
            concerns.append("Price above Bollinger upper band  -  overextended")
        elif position <= 0.0:
            score = 75.0  # Below lower band = oversold bounce potential
            label = "Below lower band"
            strengths.append("Price below Bollinger lower band  -  potential bounce")
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

        # Williams %R ranges from -100 (oversold) to 0 (overbought). Same shape
        # as RSI and MFI, so the score never jumps up when %R crosses into a band.
        if williams_r <= -80:
            score = _piecewise(williams_r, [(-100.0, 100.0), (-80.0, 70.0)])
            label = "Oversold"
        elif williams_r >= -20:
            score = _piecewise(williams_r, [(-20.0, 30.0), (0.0, 0.0)])
            label = "Overbought"
            concerns.append(f"Williams %R at {williams_r:.1f}  -  overbought zone")
        else:
            # Neutral zone: score peaks at -50
            score = _piecewise(williams_r + 100.0, OSCILLATOR_NEUTRAL)
            label = "Neutral"

        return SubScore(
            name="Williams %R",
            score=_clamp(score),
            weight=0.05,
            raw_value=williams_r,
            label=label,
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
        excluded = set(QUALITY_MODELS) - set(applicable_quality_models(ticker_info))
        quality = {k: v for k, v in quality.items() if k not in excluded}
        f_score = finite_float(quality.get("piotroski_f"))
        sub_scores.append(self._score_piotroski(f_score, strengths, concerns))

        # 2. Altman Z-Score (weight: 0.20)
        z_score = finite_float(quality.get("altman_z"))
        model = quality.get("altman_model") or "Z"
        sub_scores.append(self._score_altman_z(z_score, model, strengths, concerns))

        # 3. Revenue Growth (weight: 0.15)
        growth = analysis.get("growth_rates", {})
        revenue_growth = growth.get("revenue", {})
        rev_1y = finite_float(revenue_growth.get("1y"))
        rev_3y = finite_float(revenue_growth.get("3y_cagr"))
        sub_scores.append(self._score_revenue_growth(rev_1y, rev_3y, strengths, concerns))

        # 4. Earnings Growth (weight: 0.15)
        earnings_growth = growth.get("earnings", {})
        earn_1y = finite_float(earnings_growth.get("1y"))
        earn_3y = finite_float(earnings_growth.get("3y_cagr"))
        sub_scores.append(self._score_earnings_growth(earn_1y, earn_3y, strengths, concerns))

        # 5. Profitability / Margins (weight: 0.15)
        margins = analysis.get("margins", {}).get("current", {})
        gross_margin = finite_float(margins.get("gross_margin"))
        operating_margin = finite_float(margins.get("operating_margin"))
        sub_scores.append(
            self._score_profitability(gross_margin, operating_margin, strengths, concerns)
        )

        # 6. Return on Equity (weight: 0.10), in %. Yahoo's returnOnEquity is a
        # decimal (AAPL 1.49 = 149%); the DuPont values are already in %.
        roe_pct = None
        if ticker_info:
            roe = finite_float(ticker_info.get("roe"))
            roe_pct = roe * 100.0 if roe is not None else None
        if roe_pct is None:
            dupont = analysis.get("dupont", {})
            roe_pct = finite_float(dupont.get("roe_reported") or dupont.get("roe_calculated"))
        net_margin = finite_float(margins.get("net_margin"))
        sub_scores.append(self._score_roe(roe_pct, net_margin, strengths, concerns))

        # 7. Beneish M-Score / Earnings Manipulation (weight: 0.05)
        beneish = quality.get("beneish_m")
        sub_scores.append(self._score_beneish(beneish, strengths, concerns))

        # 8. Accruals Quality (weight: 0.05)
        accruals = quality.get("accruals_quality")
        sub_scores.append(self._score_accruals_quality(accruals, strengths, concerns))

        return _build_result("Fundamental", sub_scores, strengths, concerns)

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
            strengths.append(f"Piotroski F-Score {f_score_int}/9  -  strong fundamentals")
        elif f_score_int >= self.params.f_score_average:
            label = "Average"
        else:
            label = "Weak"
            concerns.append(f"Piotroski F-Score {f_score_int}/9  -  weak fundamentals")

        return SubScore(
            name="Piotroski F-Score",
            score=_clamp(score),
            weight=0.25,
            raw_value=float(f_score_int),
            label=label,
        )

    def _score_altman_z(
        self,
        z_score: Optional[float],
        model: str,
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if z_score is None:
            return SubScore(name="Altman Z-Score", score=50.0, weight=0.20, available=False)

        # The original Z uses the configured cut-offs; Z'' (non-manufacturers) its own
        if model == "Z":
            grey, safe = self.params.z_score_grey, self.params.z_score_safe
        else:
            grey, safe = altman_zones(model)
        # Distress 0-40, grey 40-70, safe 70-100 (reached 6 points above safe)
        score = _piecewise(z_score, [(0.0, 0.0), (grey, 40.0), (safe, 70.0), (safe + 6.0, 100.0)])
        if z_score > safe:
            label = "Safe zone"
            strengths.append(
                f"Altman {model}-Score {z_score:.2f}  -  safe zone (low bankruptcy risk)"
            )
        elif z_score > grey:
            label = "Grey zone"
        else:
            label = "Distress zone"
            concerns.append(f"Altman {model}-Score {z_score:.2f}  -  financial distress risk")
        if model != "Z":
            label += f" ({model})"

        return SubScore(
            name="Altman Z-Score",
            score=_clamp(score),
            weight=0.20,
            raw_value=z_score,
            label=label,
        )

    def _score_beneish(
        self,
        beneish_data: Optional[dict],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if beneish_data is None:
            return SubScore(name="Beneish M-Score", score=50.0, weight=0.05, available=False)

        m_score = beneish_data.get("m_score")
        if m_score is None:
            return SubScore(name="Beneish M-Score", score=50.0, weight=0.05, available=False)
        if beneish_is_partial(beneish_data):
            # Mostly defaults: the red flags show it as a weak signal; no score
            return SubScore(
                name="Beneish M-Score",
                score=50.0,
                weight=0.05,
                raw_value=m_score,
                label="Too few inputs",
                available=False,
            )

        # Lower (more negative) is better: 80 up to BENEISH_UNLIKELY, 15 from
        # BENEISH_LIKELY, a straight line across the grey zone between
        score = _piecewise(m_score, [(BENEISH_UNLIKELY, 80.0), (BENEISH_LIKELY, 15.0)])
        if m_score > BENEISH_LIKELY:
            label = "Likely manipulator"
            concerns.append(f"Beneish M-Score {m_score:.2f}  -  earnings manipulation risk")
        elif m_score > BENEISH_UNLIKELY:
            label = "Grey zone"
        else:
            label = "Unlikely manipulator"

        return SubScore(
            name="Beneish M-Score",
            score=_clamp(score),
            weight=0.05,
            raw_value=m_score,
            label=label,
        )

    def _score_accruals_quality(
        self,
        accruals_data: Optional[dict],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if accruals_data is None:
            return SubScore(name="Accruals Quality", score=50.0, weight=0.05, available=False)

        ratio = accruals_data.get("accrual_ratio_pct")
        quality = accruals_data.get("quality")
        if ratio is None:
            return SubScore(name="Accruals Quality", score=50.0, weight=0.05, available=False)

        # Negative accruals = very good (cash > reported earnings)
        # Low positive = good, High positive = bad
        if quality == "very_high":
            score = 85.0
            label = "Cash > Earnings"
        elif quality == "high":
            score = 70.0
            label = "Good quality"
        elif quality == "moderate":
            score = 45.0
            label = "Moderate quality"
        else:
            score = 20.0
            label = "Low quality"
            concerns.append(f"High accruals ({ratio:.1f}%)  -  earnings quality concern")

        return SubScore(
            name="Accruals Quality",
            score=_clamp(score),
            weight=0.05,
            raw_value=ratio,
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

        moderate, strong = self.params.revenue_growth_moderate, self.params.revenue_growth_strong
        score = _piecewise(
            growth,
            [(-30.0, 0.0), (0.0, 30.0), (moderate, 50.0), (strong, 75.0), (strong + 50.0, 100.0)],
        )
        if growth >= strong:
            label = "Strong growth"
            strengths.append(f"Revenue growth {growth:.1f}%  -  strong")
        elif growth >= moderate:
            label = "Moderate growth"
        elif growth >= 0:
            label = "Slow growth"
        else:
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

        moderate, strong = self.params.earnings_growth_moderate, self.params.earnings_growth_strong
        score = _piecewise(
            growth,
            [(-60.0, 0.0), (0.0, 30.0), (moderate, 50.0), (strong, 75.0), (strong + 62.5, 100.0)],
        )
        if growth >= strong:
            label = "Strong growth"
            strengths.append(f"Earnings growth {growth:.1f}%  -  strong")
        elif growth >= moderate:
            label = "Moderate growth"
        elif growth >= 0:
            label = "Slow growth"
        else:
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

        def margin_score(margin: float, good: float, excellent: float) -> float:
            # 35 at break-even, 60 at good, 85 from excellent; 10 at MARGIN_FLOOR
            return _piecewise(
                margin, [(MARGIN_FLOOR, 10.0), (0.0, 35.0), (good, 60.0), (excellent, 85.0)]
            )

        scores = []
        if gross_margin is not None:
            scores.append(
                margin_score(
                    gross_margin, self.params.gross_margin_good, self.params.gross_margin_excellent
                )
            )
        if operating_margin is not None:
            scores.append(
                margin_score(
                    operating_margin,
                    self.params.operating_margin_good,
                    self.params.operating_margin_excellent,
                )
            )

        score = sum(scores) / len(scores)

        if score >= 75:
            label = "Excellent margins"
            strengths.append(
                f"Strong profitability  -  gross {gross_margin:.1f}%, "
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
        self,
        roe_pct: Optional[float],
        net_margin: Optional[float],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if roe_pct is None:
            return SubScore(name="ROE", score=50.0, weight=0.10, available=False)
        # ROE and net margin of opposite signs mean negative equity: profitable
        # with a negative ROE (often from buybacks, e.g. MCD), or a loss over
        # negative equity, which reads as a positive, "excellent" ROE. Either
        # way the ratio says nothing about returns.
        if net_margin is not None and (
            (roe_pct < 0 and net_margin > 0) or (roe_pct > 0 and net_margin < 0)
        ):
            return SubScore(
                name="ROE",
                score=50.0,
                weight=0.10,
                raw_value=roe_pct,
                label="Negative equity",
                available=False,
            )

        good, excellent = self.params.roe_good, self.params.roe_excellent
        score = _piecewise(
            roe_pct,
            [
                (-25.0, 0.0),
                (0.0, 25.0),
                (good, 55.0),
                (excellent, 80.0),
                (excellent + 20 / 0.3, 100.0),
            ],
        )
        if roe_pct >= excellent:
            label = "Excellent"
            strengths.append(f"ROE {roe_pct:.1f}%  -  excellent return on equity")
        elif roe_pct >= good:
            label = "Good"
        elif roe_pct >= 0:
            label = "Low"
        else:
            label = "Negative"
            concerns.append(f"Negative ROE ({roe_pct:.1f}%)  -  company losing money on equity")

        return SubScore(
            name="ROE", score=_clamp(score), weight=0.10, raw_value=roe_pct, label=label
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
        sharpe = finite_float(risk_data.get("sharpe_ratio"))
        sub_scores.append(self._score_sharpe(sharpe, strengths, concerns))

        # 2. Sortino Ratio (weight: 0.15)
        sortino = finite_float(risk_data.get("sortino_ratio"))
        sub_scores.append(self._score_sortino(sortino, strengths, concerns))

        # 3. Maximum Drawdown (weight: 0.25)
        drawdown = risk_data.get("drawdown", {})
        max_dd = finite_float(drawdown.get("max_drawdown"))
        sub_scores.append(self._score_drawdown(max_dd, strengths, concerns))

        # 4. Beta (weight: 0.15)
        market_risk = risk_data.get("market_risk", {})
        beta = finite_float(market_risk.get("beta"))
        sub_scores.append(self._score_beta(beta, strengths, concerns))

        # 5. Volatility (weight: 0.15)
        vol_data = risk_data.get("volatility", {})
        ann_vol = finite_float(vol_data.get("annualized_volatility"))
        sub_scores.append(self._score_volatility(ann_vol, strengths, concerns))

        # 6. VaR (weight: 0.05)
        var_data = risk_data.get("var_95", {})
        var_95 = finite_float(var_data.get("var_historical"))
        sub_scores.append(self._score_var(var_95, strengths, concerns))

        return _build_result("Risk", sub_scores, strengths, concerns)

    def _score_sharpe(
        self, sharpe: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if sharpe is None:
            return SubScore(name="Sharpe Ratio", score=50.0, weight=0.25, available=False)

        acceptable = self.params.sharpe_acceptable
        good, excellent = self.params.sharpe_good, self.params.sharpe_excellent
        score = _piecewise(
            sharpe, [(-2.5, 0.0), (0.0, 25.0), (acceptable, 50.0), (good, 70.0), (excellent, 90.0)]
        )
        if sharpe >= excellent:
            label = "Excellent"
            strengths.append(f"Sharpe ratio {sharpe:.2f}  -  excellent risk-adjusted returns")
        elif sharpe >= good:
            label = "Good"
            strengths.append(f"Sharpe ratio {sharpe:.2f}  -  good risk-adjusted returns")
        elif sharpe >= acceptable:
            label = "Acceptable"
        elif sharpe >= 0:
            label = "Poor"
            concerns.append(f"Sharpe ratio {sharpe:.2f}  -  poor risk-adjusted returns")
        else:
            label = "Negative"
            concerns.append(
                f"Negative Sharpe ratio ({sharpe:.2f})  -  underperforming risk-free rate"
            )

        return SubScore(
            name="Sharpe Ratio", score=_clamp(score), weight=0.25, raw_value=sharpe, label=label
        )

    def _score_sortino(
        self, sortino: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if sortino is None:
            return SubScore(name="Sortino Ratio", score=50.0, weight=0.15, available=False)

        # Similar logic to Sharpe but typically higher values
        score = _piecewise(
            sortino,
            [
                (-4.0, 0.0),
                (0.0, 20.0),
                (SORTINO_ACCEPTABLE, 45.0),
                (SORTINO_GOOD, 70.0),
                (SORTINO_EXCELLENT, 90.0),
            ],
        )
        if sortino >= SORTINO_EXCELLENT:
            label = "Excellent"
        elif sortino >= SORTINO_GOOD:
            label = "Good"
        elif sortino >= SORTINO_ACCEPTABLE:
            label = "Acceptable"
        elif sortino >= 0:
            label = "Poor"
        else:
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

        low, moderate, high = (
            self.params.drawdown_low,
            self.params.drawdown_moderate,
            self.params.drawdown_high,
        )
        score = _piecewise(dd_abs, [(low, 90.0), (moderate, 65.0), (high, 35.0), (high + 0.7, 0.0)])
        if dd_abs <= low:
            label = "Low risk"
            strengths.append(f"Max drawdown only {dd_abs:.1%}  -  low downside risk")
        elif dd_abs <= moderate:
            label = "Moderate"
        elif dd_abs <= high:
            label = "High risk"
            concerns.append(f"Max drawdown {dd_abs:.1%}  -  significant downside risk")
        else:
            label = "Very high risk"
            concerns.append(f"Max drawdown {dd_abs:.1%}  -  severe drawdown risk")

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

        # Ideal beta: 0.7-1.3 (moderate market sensitivity). Low beta is
        # defensive, generally good but may underperform; high is aggressive
        low, high = self.params.beta_ideal_low, self.params.beta_ideal_high
        score = _piecewise(beta, [(0.0, 65.0), (low, 75.0), (high, 75.0), (high + 2.4, 15.0)])
        if low <= beta <= high:
            label = "Moderate"
        elif beta < 0:
            score = 50.0  # Negative beta is unusual
            label = "Negative (unusual)"
        elif beta < low:
            label = "Defensive"
            strengths.append(f"Beta {beta:.2f}  -  defensive, low market sensitivity")
        else:
            label = "Aggressive"
            if beta > BETA_CONCERN:
                concerns.append(f"Beta {beta:.2f}  -  highly volatile relative to market")

        return SubScore(name="Beta", score=_clamp(score), weight=0.15, raw_value=beta, label=label)

    def _score_volatility(
        self, ann_vol: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if ann_vol is None:
            return SubScore(name="Volatility", score=50.0, weight=0.15, available=False)

        low, moderate, high = (
            self.params.volatility_low,
            self.params.volatility_moderate,
            self.params.volatility_high,
        )
        score = _piecewise(
            ann_vol, [(low, 90.0), (moderate, 60.0), (high, 25.0), (high + 25 / 30, 0.0)]
        )
        if ann_vol <= low:
            label = "Low"
            strengths.append(f"Annualized volatility {ann_vol:.1%}  -  low")
        elif ann_vol <= moderate:
            label = "Moderate"
        elif ann_vol <= high:
            label = "High"
            concerns.append(f"Annualized volatility {ann_vol:.1%}  -  elevated risk")
        else:
            label = "Very high"
            concerns.append(f"Annualized volatility {ann_vol:.1%}  -  very high risk")

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

        score = _piecewise(
            var_abs,
            [(VAR_LOW, 85.0), (VAR_MODERATE, 65.0), (VAR_ELEVATED, 40.0), (VAR_HIGH, 20.0)],
        )
        if var_abs <= VAR_LOW:
            label = "Low daily risk"
        elif var_abs <= VAR_MODERATE:
            label = "Moderate daily risk"
        elif var_abs <= VAR_ELEVATED:
            label = "Elevated daily risk"
        else:
            label = "High daily risk"

        return SubScore(
            name="VaR (95%)",
            score=_clamp(score),
            weight=0.05,
            raw_value=var_95,
            label=label,
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
        peer_valuation: Optional[Dict[str, Any]] = None,
        fcf_yield: Optional[float] = None,
    ) -> DimensionResult:
        """
        Score valuation analysis data.

        Args:
            valuation_data: Output from ValuationAnalyzer.analyze() or
                           the valuation_analysis section of a full report
            ticker_info: Optional ticker info dict for P/E, P/B, PEG, etc.
            peer_valuation: Optional peer comparison (see vetting.peers); with
                           enough peers, P/E is scored against the peer median
            fcf_yield: FCF / market cap in percent, from the fundamental
                           analysis (fcf_metrics)

        Returns:
            DimensionResult with valuation dimension score
        """
        sub_scores: List[SubScore] = []
        strengths: List[str] = []
        concerns: List[str] = []

        # A free-cash-flow DCF and cash-backed earnings don't apply to banks
        # and insurers (see is_financial)
        financial = is_financial(ticker_info)

        # 1. DCF Valuation (weight: 0.25)
        dcf = valuation_data.get("dcf_valuation", {})
        dcf_premium = None if financial else finite_float(dcf.get("discount_premium_pct"))
        dcf_error = dcf.get("error")
        sub_scores.append(self._score_dcf(dcf_premium, dcf_error, strengths, concerns))

        # 2. P/E Ratio (weight: 0.20)
        pe = None
        if ticker_info:
            pe = finite_float(ticker_info.get("pe_ratio"))
        peer_median = self.peer_pe_median(peer_valuation)
        sub_scores.append(self._score_pe(pe, strengths, concerns, peer_median))

        # 3. PEG Ratio (weight: 0.15)
        peg = None
        if ticker_info:
            peg = finite_float(ticker_info.get("peg_ratio"))
        sub_scores.append(self._score_peg(peg, strengths, concerns))

        # 4. FCF Yield (weight: 0.15)
        fcf_yield = None if financial else finite_float(fcf_yield)
        sub_scores.append(self._score_fcf_yield(fcf_yield, strengths, concerns))

        # 5. Dividend Sustainability (weight: 0.10)
        div_analysis = valuation_data.get("dividend_analysis") or {}
        div_sustainability = finite_float(div_analysis.get("sustainability_score"))
        # No analysis, or one that failed, says nothing about the dividend:
        # unknown, not "No dividend" (a neutral 50 that would still count)
        pays_dividends: Optional[bool] = (
            None
            if not div_analysis or div_analysis.get("error")
            else bool(div_analysis.get("pays_dividends"))
        )
        sub_scores.append(
            self._score_dividend_sustainability(
                div_sustainability, pays_dividends, strengths, concerns
            )
        )

        # 6. Earnings Quality (weight: 0.15)
        earnings = valuation_data.get("earnings_analysis", {})
        earnings_quality_score = (
            None
            if financial
            else finite_float((earnings.get("earnings_quality") or {}).get("score"))
        )
        beat_rate = finite_float((earnings.get("surprise_stats") or {}).get("beat_rate"))
        sub_scores.append(
            self._score_earnings_quality(earnings_quality_score, beat_rate, strengths, concerns)
        )

        return _build_result("Valuation", sub_scores, strengths, concerns)

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
        deep, moderate, fair = (
            self.params.dcf_deep_discount,
            self.params.dcf_moderate_discount,
            self.params.dcf_fair_value_range,
        )
        score = _piecewise(
            premium_pct, [(deep, 90.0), (moderate, 70.0), (fair, 50.0), (fair + 150.0, 5.0)]
        )
        if premium_pct <= deep:
            label = "Deeply undervalued"
            strengths.append(
                f"DCF shows {abs(premium_pct):.0f}% discount to intrinsic value  -  deeply undervalued"
            )
        elif premium_pct <= moderate:
            label = "Undervalued"
            strengths.append(f"DCF shows {abs(premium_pct):.0f}% discount  -  undervalued")
        elif premium_pct <= fair:
            label = "Near fair value"
        else:
            label = "Overvalued"
            if premium_pct > DCF_CONCERN_PREMIUM:
                concerns.append(
                    f"DCF shows {premium_pct:.0f}% premium  -  significantly overvalued"
                )

        return SubScore(
            name="DCF Valuation",
            score=_clamp(score),
            weight=0.25,
            raw_value=premium_pct,
            label=label,
        )

    def peer_pe_median(self, peer_valuation: Optional[Dict[str, Any]]) -> Optional[float]:
        """Peer median P/E to score against, or None to use the absolute cutoffs."""
        if not self.params.peer_relative or not peer_valuation:
            return None
        pe = (peer_valuation.get("metrics") or {}).get("pe_ratio") or {}
        median = finite_float(pe.get("median"))
        if median is None or median <= 0 or (pe.get("n") or 0) < self.params.min_peers:
            return None
        return median

    def _score_pe(
        self,
        pe: Optional[float],
        strengths: List[str],
        concerns: List[str],
        peer_median: Optional[float] = None,
    ) -> SubScore:
        if pe is None or pe <= 0:
            return SubScore(name="P/E Ratio", score=50.0, weight=0.20, available=False)

        undervalued = self.params.pe_undervalued
        fair = self.params.pe_fair
        expensive = self.params.pe_expensive
        context = ""
        if peer_median is not None:
            # Same curve, rescaled so the peer median sits where pe_fair does
            scale = peer_median / fair
            undervalued, fair, expensive = undervalued * scale, peer_median, expensive * scale
            context = f" vs peer median {peer_median:.1f}"
        # The outer slopes are per P/E point on the absolute scale; rescale them too
        unit = fair / self.params.pe_fair

        score = _piecewise(
            pe,
            [
                (undervalued - 20 / 1.5 * unit, 100.0),
                (undervalued, 80.0),
                (fair, 50.0),
                (expensive, 25.0),
                (expensive + 20 / 0.3 * unit, 5.0),
            ],
        )
        if pe <= undervalued:
            label = "Attractive"
            strengths.append(f"P/E {pe:.1f}{context}  -  attractively valued")
        elif pe <= fair:
            label = "Fair"
        elif pe <= expensive:
            label = "Expensive"
        else:
            label = "Very expensive"
            concerns.append(f"P/E {pe:.1f}{context}  -  richly valued")

        if peer_median is not None:
            label += " (vs peers)"
        return SubScore(
            name="P/E Ratio", score=_clamp(score), weight=0.20, raw_value=pe, label=label
        )

    def _score_peg(
        self, peg: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if peg is None or peg <= 0:
            return SubScore(name="PEG Ratio", score=50.0, weight=0.15, available=False)

        undervalued, fair = self.params.peg_undervalued, self.params.peg_fair
        score = _piecewise(peg, [(undervalued, 85.0), (fair, 50.0), (fair + 4.0, 10.0)])
        if peg <= undervalued:
            label = "Undervalued for growth"
            strengths.append(f"PEG {peg:.2f}  -  undervalued relative to growth rate")
        elif peg <= fair:
            label = "Fair"
        else:
            label = "Expensive for growth"

        return SubScore(
            name="PEG Ratio", score=_clamp(score), weight=0.15, raw_value=peg, label=label
        )

    def _score_fcf_yield(
        self, fcf_yield: Optional[float], strengths: List[str], concerns: List[str]
    ) -> SubScore:
        if fcf_yield is None:
            return SubScore(name="FCF Yield", score=50.0, weight=0.15, available=False)

        moderate, attractive = self.params.fcf_yield_moderate, self.params.fcf_yield_attractive
        score = _piecewise(
            fcf_yield,
            [
                (FCF_YIELD_FLOOR, 10.0),
                (0.0, 25.0),
                (moderate, 50.0),
                (attractive, 80.0),
                (attractive + 10.0, 100.0),
            ],
        )
        if fcf_yield >= attractive:
            label = "Attractive"
            strengths.append(f"FCF yield {fcf_yield:.1f}%  -  strong cash generation")
        elif fcf_yield >= moderate:
            label = "Moderate"
        elif fcf_yield >= 0:
            label = "Low"
        else:
            label = "Negative (cash burn)"
            concerns.append("Negative FCF yield  -  company burning cash")

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
        pays_dividends: Optional[bool],
        strengths: List[str],
        concerns: List[str],
    ) -> SubScore:
        if pays_dividends is None:
            return SubScore(
                name="Dividend Sustainability", score=50.0, weight=0.10, available=False
            )
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
            strengths.append(f"Dividend sustainability {score:.0f}/100  -  highly sustainable")
        elif score >= self.params.div_sustainability_good:
            label = "Good"
        else:
            label = "At risk"
            concerns.append(f"Dividend sustainability {score:.0f}/100  -  may be at risk")

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
            beats = f", beat rate {beat_rate:.0f}%" if beat_rate is not None else ""
            strengths.append(f"High earnings quality{beats}")
        elif score >= 45:
            label = "Moderate quality"
        else:
            label = "Low quality"
            concerns.append("Low earnings quality  -  cash flow doesn't support reported earnings")

        return SubScore(
            name="Earnings Quality",
            score=_clamp(score),
            weight=0.15,
            raw_value=raw_value,
            label=label,
        )
