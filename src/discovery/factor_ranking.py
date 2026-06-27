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

        # Step 1: Calculate raw factor values for each ticker
        raw_factors: Dict[str, Dict[str, Optional[float]]] = {}

        for ticker, data in ticker_data.items():
            raw_factors[ticker] = {
                "value": self._calc_value_factor(data),
                "quality": self._calc_quality_factor(data),
                "momentum": self._calc_momentum_factor(data),
                "low_vol": self._calc_low_vol_factor(data),
            }

        # Step 2: Cross-sectional percentile ranking (0-100) for each factor
        factor_names = ["value", "quality", "momentum", "low_vol"]
        percentile_scores: Dict[str, Dict[str, float]] = {t: {} for t in ticker_data}

        for factor in factor_names:
            values = {
                t: raw_factors[t][factor] for t in ticker_data if raw_factors[t][factor] is not None
            }
            if len(values) < 2:
                continue

            # Rank and convert to percentile
            sorted_tickers = sorted(values.keys(), key=lambda t: values[t])
            n = len(sorted_tickers)
            for rank, t in enumerate(sorted_tickers):
                percentile_scores[t][factor] = (rank / (n - 1)) * 100 if n > 1 else 50.0

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

    def _calc_value_factor(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Value factor: composite of earnings yield, FCF yield, book/price.
        Higher = cheaper = better value.
        """
        info = data.get("info", {})
        scores = []

        # Earnings yield (inverse of P/E)
        pe = info.get("pe_ratio") or info.get("trailingPE")
        if pe and pe > 0:
            earnings_yield = 1.0 / pe
            scores.append(earnings_yield)

        # FCF yield
        report = data.get("report", {})
        fcf_metrics = (
            report.get("fundamental_analysis", {}).get("analysis", {}).get("fcf_metrics", {})
        )
        fcf_yield = fcf_metrics.get("fcf_yield")
        if fcf_yield is not None:
            scores.append(fcf_yield / 100.0)

        # Book/Price (inverse of P/B)
        pb = info.get("price_to_book") or info.get("priceToBook")
        if pb and pb > 0:
            book_to_price = 1.0 / pb
            scores.append(book_to_price)

        if not scores:
            return None

        return float(np.mean(scores))

    def _calc_quality_factor(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Quality factor: composite of ROE, low accruals, low leverage.
        Higher = better quality.
        """
        info = data.get("info", {})
        report = data.get("report", {})
        scores = []

        # ROE (higher is better, but cap at reasonable levels)
        roe = info.get("roe") or info.get("returnOnEquity")
        if roe is not None:
            # Normalize: -50% to +50% ROE → 0 to 1
            roe_normalized = max(min((roe + 0.5) / 1.0, 1.0), 0.0)
            scores.append(roe_normalized)

        # Accruals quality (lower accrual ratio = higher quality)
        quality_scores = (
            report.get("fundamental_analysis", {}).get("analysis", {}).get("quality_scores", {})
        )
        accruals = quality_scores.get("accruals_quality", {})
        accrual_ratio = accruals.get("accrual_ratio_pct")
        if accrual_ratio is not None:
            # Lower (more negative) accruals = better quality
            # Range: -50% to +20% → 1.0 to 0.0
            accrual_normalized = max(min((20.0 - accrual_ratio) / 70.0, 1.0), 0.0)
            scores.append(accrual_normalized)

        # Low leverage (lower debt/equity = better)
        de = info.get("debt_to_equity") or info.get("debtToEquity")
        if de is not None and de >= 0:
            # D/E 0 = best (1.0), D/E 3+ = worst (0.0)
            leverage_score = max(1.0 - de / 3.0, 0.0)
            scores.append(leverage_score)

        # Piotroski F-Score (0-9 → 0-1)
        f_score = quality_scores.get("piotroski_f")
        if f_score is not None:
            scores.append(f_score / 9.0)

        if not scores:
            return None

        return float(np.mean(scores))

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
        lines.append("  Scores are percentile ranks (0-100, higher = better)")
        lines.append("  Weights: Value 25%, Quality 25%, Momentum 30%, Low Vol 20%")
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
