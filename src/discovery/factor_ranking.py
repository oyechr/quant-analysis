"""
Factor-Based Screening & Ranking

Implements Fama-French-style multi-factor ranking across a ticker universe.
Ranks stocks by Value, Quality, Momentum, and Low Volatility factors,
then produces a composite percentile score.

This is the core of systematic/quantitative investing — not speed-dependent,
just mathematically rigorous factor construction.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FactorScore:
    """Individual factor score for a ticker"""

    ticker: str
    value_score: Optional[float] = None
    quality_score: Optional[float] = None
    momentum_score: Optional[float] = None
    low_vol_score: Optional[float] = None
    size_score: Optional[float] = None
    composite_score: Optional[float] = None
    percentile_rank: Optional[float] = None
    factors_available: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FactorWeights:
    """Weights for composite factor score"""

    value: float = 0.25
    quality: float = 0.25
    momentum: float = 0.30
    low_volatility: float = 0.20


class FactorRanker:
    """
    Multi-factor stock screener and ranker.

    Computes factor scores for a universe of tickers and ranks them
    using cross-sectional percentile scoring. Each factor is derived
    from widely-studied academic research:

    - Value: Earnings yield, book/price, FCF yield
    - Quality: ROE, low accruals, low debt, margin stability
    - Momentum: 12-minus-1-month return (skip recent month to avoid reversal)
    - Low Volatility: Inverse of annualized volatility
    """

    def __init__(self, weights: Optional[FactorWeights] = None):
        self.weights = weights or FactorWeights()

    def rank_universe(
        self,
        ticker_data: Dict[str, Dict[str, Any]],
    ) -> List[FactorScore]:
        """
        Rank a universe of tickers by multi-factor composite score.

        Args:
            ticker_data: Dict mapping ticker -> {
                "info": ticker_info dict,
                "price_data": DataFrame with Close prices (12+ months preferred),
                "fundamentals": fundamentals dict (optional),
                "report": full report dict (optional),
            }

        Returns:
            List of FactorScore sorted by composite rank (best first)
        """
        if len(ticker_data) < 2:
            logger.warning("Need at least 2 tickers for cross-sectional ranking")
            return []

        # Step 1: Raw factor components per ticker. Value and quality blend several
        # metrics on different scales (earnings yield ~0.05 vs book/price ~0.5), so
        # each component is ranked on its own before averaging.
        components: Dict[str, Dict[str, Dict[str, float]]] = {
            t: {
                "value": self._value_components(data),
                "quality": self._quality_components(data),
                "momentum": _single("momentum_12_1", self._calc_momentum_factor(data)),
                "low_vol": _single("inverse_vol", self._calc_low_vol_factor(data)),
            }
            for t, data in ticker_data.items()
        }
        raw_factors: Dict[str, Dict[str, Optional[float]]] = {
            t: {
                "value": self._calc_value_factor(data),
                "quality": self._calc_quality_factor(data),
                "momentum": components[t]["momentum"].get("momentum_12_1"),
                "low_vol": components[t]["low_vol"].get("inverse_vol"),
            }
            for t, data in ticker_data.items()
        }

        # Step 2: Cross-sectional percentile (0-100) per component, averaged per factor
        factor_names = ["value", "quality", "momentum", "low_vol"]
        percentile_scores: Dict[str, Dict[str, float]] = {t: {} for t in ticker_data}

        for factor in factor_names:
            component_names = {name for t in ticker_data for name in components[t][factor]}
            component_pcts: Dict[str, List[float]] = {t: [] for t in ticker_data}
            for name in component_names:
                values = {
                    t: components[t][factor][name]
                    for t in ticker_data
                    if name in components[t][factor]
                }
                for t, pct in _percentiles(values).items():
                    component_pcts[t].append(pct)
            for t, pcts in component_pcts.items():
                if pcts:
                    percentile_scores[t][factor] = float(np.mean(pcts))

        # Step 3: Weighted composite score
        results: List[FactorScore] = []

        for ticker in ticker_data:
            scores = percentile_scores[ticker]
            factors_available = len(scores)

            value_pct = scores.get("value")
            quality_pct = scores.get("quality")
            momentum_pct = scores.get("momentum")
            low_vol_pct = scores.get("low_vol")

            # Compute weighted composite (only using available factors)
            weighted_sum = 0.0
            weight_sum = 0.0

            if value_pct is not None:
                weighted_sum += value_pct * self.weights.value
                weight_sum += self.weights.value
            if quality_pct is not None:
                weighted_sum += quality_pct * self.weights.quality
                weight_sum += self.weights.quality
            if momentum_pct is not None:
                weighted_sum += momentum_pct * self.weights.momentum
                weight_sum += self.weights.momentum
            if low_vol_pct is not None:
                weighted_sum += low_vol_pct * self.weights.low_volatility
                weight_sum += self.weights.low_volatility

            composite = (weighted_sum / weight_sum) if weight_sum > 0 else None

            results.append(
                FactorScore(
                    ticker=ticker,
                    value_score=value_pct,
                    quality_score=quality_pct,
                    momentum_score=momentum_pct,
                    low_vol_score=low_vol_pct,
                    composite_score=composite,
                    factors_available=factors_available,
                    details={
                        "raw_value": raw_factors[ticker]["value"],
                        "raw_quality": raw_factors[ticker]["quality"],
                        "raw_momentum": raw_factors[ticker]["momentum"],
                        "raw_low_vol": raw_factors[ticker]["low_vol"],
                    },
                )
            )

        # Step 4: Final composite percentile rank
        scored = [r for r in results if r.composite_score is not None]
        scored.sort(key=lambda r: r.composite_score)  # type: ignore[arg-type]
        n = len(scored)
        for rank, r in enumerate(scored):
            r.percentile_rank = (rank / (n - 1)) * 100 if n > 1 else 50.0

        # Sort best first (highest composite)
        results.sort(key=lambda r: r.composite_score or 0, reverse=True)
        return results

    def _value_components(self, data: Dict[str, Any]) -> Dict[str, float]:
        """Value metrics (higher = cheaper): earnings yield, FCF yield, book/price."""
        info = data.get("info", {})
        components: Dict[str, float] = {}

        pe = info.get("pe_ratio") or info.get("trailingPE")
        if pe and pe > 0:
            components["earnings_yield"] = 1.0 / pe

        report = data.get("report") or {}
        fcf_metrics = (
            (report.get("fundamental_analysis") or {}).get("analysis", {}).get("fcf_metrics", {})
        )
        fcf_yield = fcf_metrics.get("fcf_yield")
        if fcf_yield is not None:
            components["fcf_yield"] = fcf_yield / 100.0

        pb = info.get("price_to_book") or info.get("priceToBook")
        if pb and pb > 0:
            components["book_to_price"] = 1.0 / pb

        return components

    def _calc_value_factor(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Value factor: composite of earnings yield, FCF yield, book/price.
        Higher = cheaper = better value.
        """
        components = self._value_components(data)
        return float(np.mean(list(components.values()))) if components else None

    def _quality_components(self, data: Dict[str, Any]) -> Dict[str, float]:
        """
        Quality metrics, each oriented so higher = better, normalized to 0-1:
        ROE, low accruals, low leverage, Piotroski F-Score.
        """
        info = data.get("info", {})
        report = data.get("report") or {}
        components: Dict[str, float] = {}

        # ROE: -50% to +50% -> 0 to 1 (caps outliers from tiny equity bases)
        roe = info.get("roe") or info.get("returnOnEquity")
        if roe is not None:
            components["roe"] = max(min((roe + 0.5) / 1.0, 1.0), 0.0)

        quality_scores = (
            (report.get("fundamental_analysis") or {}).get("analysis", {}).get("quality_scores", {})
        )
        # Accruals: -50% to +20% -> 1.0 to 0.0 (lower accruals = earnings backed by cash)
        accrual_ratio = (quality_scores.get("accruals_quality") or {}).get("accrual_ratio_pct")
        if accrual_ratio is not None:
            components["low_accruals"] = max(min((20.0 - accrual_ratio) / 70.0, 1.0), 0.0)

        # Leverage: Yahoo reports debt/equity as a percentage (150 = 1.5x).
        # D/E 0x = 1.0, 3x+ = 0.0
        de_pct = info.get("debt_to_equity")
        if de_pct is None:
            de_pct = info.get("debtToEquity")
        if de_pct is not None and de_pct >= 0:
            components["low_leverage"] = max(1.0 - (de_pct / 100.0) / 3.0, 0.0)

        # Piotroski F-Score (0-9 -> 0-1)
        f_score = quality_scores.get("piotroski_f")
        if f_score is not None:
            components["piotroski"] = f_score / 9.0

        return components

    def _calc_quality_factor(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Quality factor: composite of ROE, low accruals, low leverage, F-Score.
        Higher = better quality.
        """
        components = self._quality_components(data)
        return float(np.mean(list(components.values()))) if components else None

    def _calc_momentum_factor(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Momentum factor: 12-minus-1-month return.
        Skip the most recent month (proven to remove short-term reversal noise).
        Higher past returns = better momentum.
        """
        price_data = data.get("price_data")
        if price_data is None or price_data.empty or len(price_data) < 60:
            return None

        try:
            prices = price_data["Close"]

            # Skip most recent 21 trading days (~1 month)
            # Then measure return over prior ~11 months
            if len(prices) < 42:  # Need at least 2 months
                return None

            price_end = float(prices.iloc[-22])  # ~1 month ago
            # Go back as far as possible (up to 252 days for 12-month)
            lookback = min(len(prices) - 1, 252)
            price_start = float(prices.iloc[-lookback])

            if price_start <= 0:
                return None

            # 12-minus-1 month return
            momentum_return = (price_end - price_start) / price_start
            return momentum_return

        except Exception as e:
            logger.warning(f"Momentum calculation failed: {e}")
            return None

    def _calc_low_vol_factor(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Low Volatility factor: inverse of annualized volatility.
        Lower volatility = higher score (low-vol anomaly).
        """
        price_data = data.get("price_data")
        if price_data is None or price_data.empty or len(price_data) < 60:
            return None

        try:
            daily_returns = price_data["Close"].pct_change().dropna()
            if daily_returns.empty:
                return None

            annualized_vol = float(daily_returns.std()) * np.sqrt(252)

            if annualized_vol <= 0:
                return None

            # Inverse: lower vol = higher factor value
            return 1.0 / annualized_vol

        except Exception as e:
            logger.warning(f"Low-vol calculation failed: {e}")
            return None

    def format_rankings(self, results: List[FactorScore]) -> str:
        """Format factor rankings as a readable table"""
        if not results:
            return "No rankings available"

        lines = []
        lines.append("=" * 72)
        lines.append("  MULTI-FACTOR RANKING")
        lines.append("=" * 72)
        lines.append("")
        lines.append(
            f"  {'Rank':<5} {'Ticker':<8} {'Composite':<10} "
            f"{'Value':<8} {'Quality':<8} {'Momentum':<10} {'Low Vol':<8}"
        )
        lines.append("  " + "-" * 65)

        for i, r in enumerate(results, 1):
            composite = f"{r.composite_score:.0f}" if r.composite_score is not None else "N/A"
            value = f"{r.value_score:.0f}" if r.value_score is not None else "-"
            quality = f"{r.quality_score:.0f}" if r.quality_score is not None else "-"
            momentum = f"{r.momentum_score:.0f}" if r.momentum_score is not None else "-"
            low_vol = f"{r.low_vol_score:.0f}" if r.low_vol_score is not None else "-"

            lines.append(
                f"  {i:<5} {r.ticker:<8} {composite:<10} "
                f"{value:<8} {quality:<8} {momentum:<10} {low_vol:<8}"
            )

        lines.append("")
        w = self.weights
        lines.append("  Scores are percentile ranks (0-100, higher = better)")
        lines.append(
            f"  Weights: Value {w.value:.0%}, Quality {w.quality:.0%}, "
            f"Momentum {w.momentum:.0%}, Low Vol {w.low_volatility:.0%}"
        )
        lines.append("")
        return "\n".join(lines)

    def to_dict(self, results: List[FactorScore]) -> List[Dict[str, Any]]:
        """Convert results to JSON-serializable list"""
        return [
            {
                "rank": i + 1,
                "ticker": r.ticker,
                "composite_score": r.composite_score,
                "percentile_rank": r.percentile_rank,
                "factors": {
                    "value": r.value_score,
                    "quality": r.quality_score,
                    "momentum": r.momentum_score,
                    "low_volatility": r.low_vol_score,
                },
                "factors_available": r.factors_available,
                "raw_values": r.details,
            }
            for i, r in enumerate(results)
        ]


def _single(name: str, value: Optional[float]) -> Dict[str, float]:
    return {name: value} if value is not None else {}


def _percentiles(values: Dict[str, float]) -> Dict[str, float]:
    """
    Cross-sectional percentile rank (0-100) of each value; ties share a rank.
    Needs at least 2 values to be meaningful.
    """
    if len(values) < 2:
        return {}
    ranks = pd.Series(values, dtype=float).rank(method="average")
    n = len(ranks)
    return {t: float((r - 1) / (n - 1) * 100) for t, r in ranks.items()}
