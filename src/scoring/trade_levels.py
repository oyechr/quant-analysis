"""
Trade Levels Calculator
Generates scenario-based entry/exit price levels for bullish and bearish contexts.
Synthesizes technical levels (support/resistance), valuation targets, and ATR-based stops.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ScenarioLevels:
    """Entry/exit levels for a single scenario (bullish or bearish)"""

    scenario: str  # "bullish" or "bearish"
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    target: Optional[float] = None
    stop_loss: Optional[float] = None
    reward_risk_ratio: Optional[float] = None

    # Sources/reasoning for each level
    entry_basis: str = ""
    target_basis: str = ""
    stop_basis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary"""
        result: Dict[str, Any] = {"scenario": self.scenario}

        if self.entry_low is not None:
            result["entry_zone"] = {
                "low": round(self.entry_low, 2),
                "high": round(self.entry_high or self.entry_low, 2),
            }
            result["entry_basis"] = self.entry_basis

        if self.target is not None:
            result["target"] = round(self.target, 2)
            result["target_basis"] = self.target_basis

        if self.stop_loss is not None:
            result["stop_loss"] = round(self.stop_loss, 2)
            result["stop_basis"] = self.stop_basis

        if self.reward_risk_ratio is not None:
            result["reward_risk_ratio"] = round(self.reward_risk_ratio, 2)

        return result


@dataclass
class TradeLevelsResult:
    """Complete trade levels output for a stock"""

    current_price: float
    currency: str = "USD"
    bullish: Optional[ScenarioLevels] = None
    bearish: Optional[ScenarioLevels] = None

    # Key technical levels used
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    atr: Optional[float] = None
    atr_multiplier: float = 2.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary"""
        result: Dict[str, Any] = {
            "current_price": round(self.current_price, 2),
            "currency": self.currency,
        }

        if self.support_levels:
            result["support_levels"] = [round(s, 2) for s in self.support_levels[:3]]
        if self.resistance_levels:
            result["resistance_levels"] = [round(r, 2) for r in self.resistance_levels[:3]]
        if self.atr is not None:
            result["atr_14"] = round(self.atr, 2)

        if self.bullish:
            result["bullish"] = self.bullish.to_dict()
        if self.bearish:
            result["bearish"] = self.bearish.to_dict()

        return result

    def format_scorecard(self) -> str:
        """Format as human-readable text block for the scoring report"""
        from ..utils.report import get_currency_symbol

        sym = get_currency_symbol(self.currency)
        lines = []
        lines.append("-" * 60)
        lines.append("  TRADE LEVELS (scenario-based, not predictions)")
        lines.append("-" * 60)
        lines.append(f"  Current Price:  {sym}{self.current_price:.2f}")
        if self.atr is not None:
            lines.append(f"  ATR (14):       {sym}{self.atr:.2f}")
        lines.append("")

        if self.bullish:
            lines.append("  Bullish Scenario:")
            if self.bullish.entry_low is not None:
                if self.bullish.entry_high and self.bullish.entry_high != self.bullish.entry_low:
                    lines.append(
                        f"    Entry Zone:   {sym}{self.bullish.entry_low:.2f} - "
                        f"{sym}{self.bullish.entry_high:.2f}  ({self.bullish.entry_basis})"
                    )
                else:
                    lines.append(
                        f"    Entry:        {sym}{self.bullish.entry_low:.2f}  "
                        f"({self.bullish.entry_basis})"
                    )
            if self.bullish.target is not None:
                lines.append(
                    f"    Target:       {sym}{self.bullish.target:.2f}  "
                    f"({self.bullish.target_basis})"
                )
            if self.bullish.stop_loss is not None:
                lines.append(
                    f"    Stop-Loss:    {sym}{self.bullish.stop_loss:.2f}  "
                    f"({self.bullish.stop_basis})"
                )
            if self.bullish.reward_risk_ratio is not None:
                lines.append(f"    R:R Ratio:    {self.bullish.reward_risk_ratio:.1f}:1")
            lines.append("")

        if self.bearish:
            lines.append("  Bearish Scenario:")
            if self.bearish.entry_low is not None:
                if self.bearish.entry_high and self.bearish.entry_high != self.bearish.entry_low:
                    lines.append(
                        f"    Entry Zone:   {sym}{self.bearish.entry_low:.2f} - "
                        f"{sym}{self.bearish.entry_high:.2f}  ({self.bearish.entry_basis})"
                    )
                else:
                    lines.append(
                        f"    Entry:        {sym}{self.bearish.entry_low:.2f}  "
                        f"({self.bearish.entry_basis})"
                    )
            if self.bearish.target is not None:
                lines.append(
                    f"    Target:       {sym}{self.bearish.target:.2f}  "
                    f"({self.bearish.target_basis})"
                )
            if self.bearish.stop_loss is not None:
                lines.append(
                    f"    Stop-Loss:    {sym}{self.bearish.stop_loss:.2f}  "
                    f"({self.bearish.stop_basis})"
                )
            if self.bearish.reward_risk_ratio is not None:
                lines.append(f"    R:R Ratio:    {self.bearish.reward_risk_ratio:.1f}:1")
            lines.append("")

        return "\n".join(lines)

    def format_markdown(self) -> List[str]:
        """Format as markdown lines for the report"""
        from ..utils.report import get_currency_symbol

        sym = get_currency_symbol(self.currency)
        md = []
        md.append("### Trade Levels")
        md.append("")
        md.append(
            "*Scenario-based levels derived from technical structure and valuation. "
            "Not predictions — use as reference for trade planning.*"
        )
        md.append("")

        if self.support_levels or self.resistance_levels:
            md.append("**Key Levels:**")
            md.append("")
            if self.resistance_levels:
                r_str = ", ".join(f"{sym}{r:.2f}" for r in self.resistance_levels[:3])
                md.append(f"- Resistance: {r_str}")
            if self.support_levels:
                s_str = ", ".join(f"{sym}{s:.2f}" for s in self.support_levels[:3])
                md.append(f"- Support: {s_str}")
            if self.atr is not None:
                md.append(f"- ATR (14): {sym}{self.atr:.2f}")
            md.append("")

        # Build scenario table
        if self.bullish or self.bearish:
            md.append("| | Bullish Scenario | Bearish Scenario |")
            md.append("|---|---|---|")

            # Entry row
            bull_entry = self._format_entry(self.bullish, sym) if self.bullish else "—"
            bear_entry = self._format_entry(self.bearish, sym) if self.bearish else "—"
            md.append(f"| **Entry** | {bull_entry} | {bear_entry} |")

            # Target row
            bull_target = (
                f"{sym}{self.bullish.target:.2f} ({self.bullish.target_basis})"
                if self.bullish and self.bullish.target
                else "—"
            )
            bear_target = (
                f"{sym}{self.bearish.target:.2f} ({self.bearish.target_basis})"
                if self.bearish and self.bearish.target
                else "—"
            )
            md.append(f"| **Target** | {bull_target} | {bear_target} |")

            # Stop-loss row
            bull_stop = (
                f"{sym}{self.bullish.stop_loss:.2f} ({self.bullish.stop_basis})"
                if self.bullish and self.bullish.stop_loss
                else "—"
            )
            bear_stop = (
                f"{sym}{self.bearish.stop_loss:.2f} ({self.bearish.stop_basis})"
                if self.bearish and self.bearish.stop_loss
                else "—"
            )
            md.append(f"| **Stop-Loss** | {bull_stop} | {bear_stop} |")

            # R:R row
            bull_rr = (
                f"{self.bullish.reward_risk_ratio:.1f}:1"
                if self.bullish and self.bullish.reward_risk_ratio
                else "—"
            )
            bear_rr = (
                f"{self.bearish.reward_risk_ratio:.1f}:1"
                if self.bearish and self.bearish.reward_risk_ratio
                else "—"
            )
            md.append(f"| **R:R Ratio** | {bull_rr} | {bear_rr} |")
            md.append("")

        return md

    @staticmethod
    def _format_entry(scenario: ScenarioLevels, sym: str) -> str:
        """Format entry zone for table display"""
        if scenario.entry_low is None:
            return "—"
        if scenario.entry_high and scenario.entry_high != scenario.entry_low:
            return (
                f"{sym}{scenario.entry_low:.2f}–{sym}{scenario.entry_high:.2f} "
                f"({scenario.entry_basis})"
            )
        return f"{sym}{scenario.entry_low:.2f} ({scenario.entry_basis})"


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely convert a value to float"""
    if value is None:
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def calculate_support_resistance(
    price_data: pd.DataFrame,
    window: int = 20,
    num_levels: int = 3,
) -> Tuple[List[float], List[float]]:
    """
    Calculate support and resistance levels from price data using pivot point clustering.

    Identifies local minima (support) and maxima (resistance) then clusters nearby
    levels together, weighting by recency and touch count.

    Args:
        price_data: DataFrame with High, Low, Close columns
        window: Window size for detecting local extrema
        num_levels: Maximum number of levels to return per side

    Returns:
        Tuple of (support_levels, resistance_levels), sorted by proximity to current price
    """
    if price_data is None or price_data.empty or len(price_data) < window * 2:
        return [], []

    highs = price_data["High"].values
    lows = price_data["Low"].values
    close = price_data["Close"].values
    current_price = float(close[-1])

    if math.isnan(current_price):
        # Fallback: find last non-NaN close
        valid_closes = price_data["Close"].dropna()
        if valid_closes.empty:
            return [], []
        current_price = float(valid_closes.iloc[-1])

    # Find local maxima (resistance candidates)
    resistance_candidates = []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            if not math.isnan(highs[i]):
                resistance_candidates.append((float(highs[i]), i))

    # Find local minima (support candidates)
    support_candidates = []
    for i in range(window, len(lows) - window):
        if lows[i] == min(lows[i - window : i + window + 1]):
            if not math.isnan(lows[i]):
                support_candidates.append((float(lows[i]), i))

    # Cluster nearby levels (within 2% of each other)
    def cluster_levels(
        candidates: List[Tuple[float, int]], threshold_pct: float = 0.02
    ) -> List[float]:
        if not candidates:
            return []

        # Sort by price
        sorted_cands = sorted(candidates, key=lambda x: x[0])
        clusters: List[List[Tuple[float, int]]] = []
        current_cluster: List[Tuple[float, int]] = [sorted_cands[0]]

        for price, idx in sorted_cands[1:]:
            cluster_mean = sum(p for p, _ in current_cluster) / len(current_cluster)
            if abs(price - cluster_mean) / cluster_mean <= threshold_pct:
                current_cluster.append((price, idx))
            else:
                clusters.append(current_cluster)
                current_cluster = [(price, idx)]
        clusters.append(current_cluster)

        # Score clusters by: touch count + recency
        scored = []
        total_bars = len(highs)
        for cluster in clusters:
            touch_count = len(cluster)
            # Recency: weight more recent touches higher
            recency_score = sum((idx / total_bars) for _, idx in cluster) / touch_count
            avg_price = sum(p for p, _ in cluster) / touch_count
            score = touch_count * 0.6 + recency_score * 0.4
            scored.append((avg_price, score))

        # Sort by score (highest first) and return prices
        scored.sort(key=lambda x: x[1], reverse=True)
        return [price for price, _ in scored]

    all_resistance = cluster_levels(resistance_candidates)
    all_support = cluster_levels(support_candidates)

    # Filter: resistance must be above current price, support below
    resistance_levels = sorted(
        [r for r in all_resistance if r > current_price * 1.005],
        key=lambda x: x,  # Closest first
    )[:num_levels]

    support_levels = sorted(
        [s for s in all_support if s < current_price * 0.995],
        key=lambda x: -x,  # Closest first (highest support first)
    )[:num_levels]

    return support_levels, resistance_levels


def calculate_trade_levels(
    current_price: float,
    currency: str = "USD",
    atr: Optional[float] = None,
    support_levels: Optional[List[float]] = None,
    resistance_levels: Optional[List[float]] = None,
    fair_value: Optional[float] = None,
    fair_value_source: str = "DCF",
    bb_lower: Optional[float] = None,
    bb_upper: Optional[float] = None,
    sma_50: Optional[float] = None,
    sma_200: Optional[float] = None,
    atr_multiplier: float = 2.0,
) -> Optional[TradeLevelsResult]:
    """
    Calculate trade levels for bullish and bearish scenarios.

    Synthesizes technical levels, valuation targets, and ATR-based stops into
    actionable entry/exit zones.

    Args:
        current_price: Current stock price
        currency: Currency code
        atr: 14-period Average True Range (for stop distance)
        support_levels: List of support levels (closest first)
        resistance_levels: List of resistance levels (closest first)
        fair_value: Intrinsic value estimate (from DCF/DDM)
        fair_value_source: Label for fair value source
        bb_lower: Bollinger Band lower value
        bb_upper: Bollinger Band upper value
        sma_50: 50-day SMA
        sma_200: 200-day SMA
        atr_multiplier: Multiplier for ATR-based stops (default 2.0)

    Returns:
        TradeLevelsResult or None if insufficient data
    """
    if current_price is None or current_price <= 0 or math.isnan(current_price):
        return None

    # Need at minimum ATR or support/resistance to produce useful levels
    supports = support_levels or []
    resistances = resistance_levels or []

    if atr is None and not supports and not resistances:
        return None

    result = TradeLevelsResult(
        current_price=current_price,
        currency=currency,
        support_levels=supports,
        resistance_levels=resistances,
        atr=atr,
        atr_multiplier=atr_multiplier,
    )

    # ===== BULLISH SCENARIO =====
    bullish = ScenarioLevels(scenario="bullish")

    # Entry zone: nearest support or BB lower or pullback to key MA
    entry_candidates: List[Tuple[float, str]] = []
    if supports:
        entry_candidates.append((supports[0], "nearest support"))
    if bb_lower is not None and not math.isnan(bb_lower):
        entry_candidates.append((bb_lower, "BB lower"))
    if sma_50 is not None and not math.isnan(sma_50) and sma_50 < current_price:
        entry_candidates.append((sma_50, "SMA 50"))
    if sma_200 is not None and not math.isnan(sma_200) and sma_200 < current_price:
        entry_candidates.append((sma_200, "SMA 200"))

    if entry_candidates:
        # Pick the level closest to current price (best entry)
        entry_candidates.sort(key=lambda x: abs(x[0] - current_price))
        best_entry_price, best_entry_basis = entry_candidates[0]
        bullish.entry_low = best_entry_price

        # If there's a second candidate nearby, create a zone
        if len(entry_candidates) > 1:
            second_price, second_basis = entry_candidates[1]
            if abs(second_price - best_entry_price) / current_price < 0.05:
                bullish.entry_low = min(best_entry_price, second_price)
                bullish.entry_high = max(best_entry_price, second_price)
                bullish.entry_basis = f"{best_entry_basis} / {second_basis}"
            else:
                bullish.entry_high = best_entry_price
                bullish.entry_basis = best_entry_basis
        else:
            bullish.entry_high = best_entry_price
            bullish.entry_basis = best_entry_basis
    else:
        # Fallback: current price is the entry
        bullish.entry_low = current_price
        bullish.entry_high = current_price
        bullish.entry_basis = "current price"

    # Target: fair value, resistance, or BB upper
    target_candidates: List[Tuple[float, str]] = []
    if fair_value is not None and not math.isnan(fair_value) and fair_value > current_price:
        target_candidates.append((fair_value, fair_value_source))
    if resistances:
        target_candidates.append((resistances[0], "resistance"))
    if bb_upper is not None and not math.isnan(bb_upper) and bb_upper > current_price:
        target_candidates.append((bb_upper, "BB upper"))

    if target_candidates:
        # Prefer fair value if significantly above, otherwise nearest resistance
        target_candidates.sort(key=lambda x: x[0], reverse=True)
        # Pick the most conservative (lowest) target that's still above entry
        for target_price, target_basis in sorted(target_candidates, key=lambda x: x[0]):
            if target_price > current_price * 1.02:  # At least 2% above
                bullish.target = target_price
                bullish.target_basis = target_basis
                break
        if bullish.target is None and target_candidates:
            bullish.target = target_candidates[0][0]
            bullish.target_basis = target_candidates[0][1]

    # Stop-loss: below nearest support by ATR, or 2x ATR below entry
    entry_ref = bullish.entry_low or current_price
    if atr is not None and supports:
        bullish.stop_loss = supports[0] - (atr * atr_multiplier * 0.5)
        bullish.stop_basis = f"below support - {atr_multiplier / 2:.1f}x ATR"
    elif atr is not None:
        bullish.stop_loss = entry_ref - (atr * atr_multiplier)
        bullish.stop_basis = f"{atr_multiplier:.1f}x ATR below entry"
    elif supports and len(supports) > 1:
        bullish.stop_loss = supports[1]  # Next support down
        bullish.stop_basis = "second support level"

    # R:R ratio
    if bullish.target and bullish.stop_loss and bullish.entry_low:
        entry_mid = (bullish.entry_low + (bullish.entry_high or bullish.entry_low)) / 2
        reward = bullish.target - entry_mid
        risk = entry_mid - bullish.stop_loss
        if risk > 0:
            bullish.reward_risk_ratio = reward / risk

    result.bullish = bullish

    # ===== BEARISH SCENARIO =====
    bearish = ScenarioLevels(scenario="bearish")

    # Entry zone: nearest resistance or BB upper or rally to key MA
    bear_entry_candidates: List[Tuple[float, str]] = []
    if resistances:
        bear_entry_candidates.append((resistances[0], "resistance"))
    if bb_upper is not None and not math.isnan(bb_upper) and bb_upper > current_price:
        bear_entry_candidates.append((bb_upper, "BB upper"))
    if sma_50 is not None and not math.isnan(sma_50) and sma_50 > current_price:
        bear_entry_candidates.append((sma_50, "SMA 50"))
    # Also allow entry at current price if already bearish
    bear_entry_candidates.append((current_price, "current price"))

    if bear_entry_candidates:
        bear_entry_candidates.sort(key=lambda x: abs(x[0] - current_price))
        best_entry_price, best_entry_basis = bear_entry_candidates[0]
        bearish.entry_low = best_entry_price

        if len(bear_entry_candidates) > 1:
            second_price, second_basis = bear_entry_candidates[1]
            if abs(second_price - best_entry_price) / current_price < 0.05:
                bearish.entry_low = min(best_entry_price, second_price)
                bearish.entry_high = max(best_entry_price, second_price)
                bearish.entry_basis = f"{best_entry_basis} / {second_basis}"
            else:
                bearish.entry_high = best_entry_price
                bearish.entry_basis = best_entry_basis
        else:
            bearish.entry_high = best_entry_price
            bearish.entry_basis = best_entry_basis

    # Target: nearest support or fair value below current
    bear_target_candidates: List[Tuple[float, str]] = []
    if supports:
        bear_target_candidates.append((supports[0], "support"))
    if fair_value is not None and not math.isnan(fair_value) and fair_value < current_price:
        bear_target_candidates.append((fair_value, fair_value_source))
    if bb_lower is not None and not math.isnan(bb_lower) and bb_lower < current_price:
        bear_target_candidates.append((bb_lower, "BB lower"))

    if bear_target_candidates:
        # Pick the most conservative (highest) target that's still below current
        for target_price, target_basis in sorted(
            bear_target_candidates, key=lambda x: x[0], reverse=True
        ):
            if target_price < current_price * 0.98:  # At least 2% below
                bearish.target = target_price
                bearish.target_basis = target_basis
                break
        if bearish.target is None and bear_target_candidates:
            bearish.target = bear_target_candidates[-1][0]
            bearish.target_basis = bear_target_candidates[-1][1]

    # Stop-loss: above nearest resistance by ATR
    bear_entry_ref = bearish.entry_high or current_price
    if atr is not None and resistances:
        bearish.stop_loss = resistances[0] + (atr * atr_multiplier * 0.5)
        bearish.stop_basis = f"above resistance + {atr_multiplier / 2:.1f}x ATR"
    elif atr is not None:
        bearish.stop_loss = bear_entry_ref + (atr * atr_multiplier)
        bearish.stop_basis = f"{atr_multiplier:.1f}x ATR above entry"
    elif resistances and len(resistances) > 1:
        bearish.stop_loss = resistances[1]  # Next resistance up
        bearish.stop_basis = "second resistance level"

    # R:R ratio (for short: reward = entry - target, risk = stop - entry)
    if bearish.target and bearish.stop_loss and bearish.entry_high:
        entry_mid = (
            (bearish.entry_low + bearish.entry_high) / 2
            if bearish.entry_low
            else bearish.entry_high
        )
        reward = entry_mid - bearish.target
        risk = bearish.stop_loss - entry_mid
        if risk > 0:
            bearish.reward_risk_ratio = reward / risk

    result.bearish = bearish

    return result


def compute_trade_levels_from_report(
    report_data: Dict[str, Any],
    atr_multiplier: float = 2.0,
) -> Optional[TradeLevelsResult]:
    """
    Compute trade levels from a full report data dictionary.
    This is the main integration point — called after scoring is complete.

    Args:
        report_data: Full report dict (same structure as ReportGenerator output)
        atr_multiplier: ATR multiplier for stop placement

    Returns:
        TradeLevelsResult or None if insufficient data
    """
    # Extract current price
    info = report_data.get("info", {})
    current_price = _safe_float(info.get("currentPrice"))
    currency = info.get("currency", "USD")

    # Fallback: get from technical analysis
    tech_data = report_data.get("technical_analysis", {})
    if current_price is None:
        latest_values = tech_data.get("latest_values", {})
        current_price = _safe_float(latest_values.get("close_price"))

    # Fallback: get from price statistics
    if current_price is None:
        stats = tech_data.get("statistics", {})
        current_price = _safe_float(stats.get("price", {}).get("current"))

    # Fallback: get from support_resistance section (uses last valid close)
    if current_price is None:
        sr_data = tech_data.get("support_resistance", {})
        current_price = _safe_float(sr_data.get("current_price"))

    if current_price is None:
        logger.warning("Cannot compute trade levels: no current price available")
        return None

    # Extract technical indicators
    indicators = tech_data.get("latest_values", {}).get("indicators", {})
    atr = _safe_float(indicators.get("ATR_14"))
    bb_lower = _safe_float(indicators.get("BB_lower"))
    bb_upper = _safe_float(indicators.get("BB_upper"))
    sma_50 = _safe_float(indicators.get("SMA_50"))
    sma_200 = _safe_float(indicators.get("SMA_200"))

    # Extract fair value from valuation
    fair_value = None
    fair_value_source = ""
    val_data = report_data.get("valuation_analysis", {})
    if val_data:
        # Try DCF first
        dcf = val_data.get("dcf_valuation", {})
        dcf_val = _safe_float(dcf.get("intrinsic_value_per_share"))
        if dcf_val and dcf_val > 0:
            fair_value = dcf_val
            fair_value_source = "DCF"

        # Try DDM if no DCF
        if fair_value is None:
            ddm = val_data.get("ddm_valuation", {})
            ddm_val = _safe_float(ddm.get("intrinsic_value_per_share"))
            if ddm_val and ddm_val > 0:
                fair_value = ddm_val
                fair_value_source = "DDM"

        # Try Monte Carlo median
        if fair_value is None:
            mc = val_data.get("monte_carlo_valuation", {})
            mc_val = _safe_float(mc.get("intrinsic_value_median"))
            if mc_val and mc_val > 0:
                fair_value = mc_val
                fair_value_source = "Monte Carlo"

    # Calculate support/resistance from price data
    support_levels: List[float] = []
    resistance_levels: List[float] = []

    # First: use pivot-based S/R from technical analysis if available
    sr_data = tech_data.get("support_resistance", {})
    if sr_data:
        pivot_supports = [_safe_float(s) for s in sr_data.get("support_levels", [])]
        pivot_resistances = [_safe_float(r) for r in sr_data.get("resistance_levels", [])]
        support_levels.extend([s for s in pivot_supports if s is not None])
        resistance_levels.extend([r for r in pivot_resistances if r is not None])

    # Supplement with MAs, Bollinger bands, and period extremes
    price_stats = tech_data.get("statistics", {}).get("price", {})
    period_high = _safe_float(price_stats.get("high"))
    period_low = _safe_float(price_stats.get("low"))

    if sma_200 is not None and sma_200 < current_price:
        support_levels.append(sma_200)
    if sma_50 is not None and sma_50 < current_price:
        support_levels.append(sma_50)
    if bb_lower is not None and bb_lower < current_price:
        support_levels.append(bb_lower)
    if period_low is not None and period_low < current_price * 0.98:
        support_levels.append(period_low)

    if sma_200 is not None and sma_200 > current_price:
        resistance_levels.append(sma_200)
    if sma_50 is not None and sma_50 > current_price:
        resistance_levels.append(sma_50)
    if bb_upper is not None and bb_upper > current_price:
        resistance_levels.append(bb_upper)
    if period_high is not None and period_high > current_price * 1.02:
        resistance_levels.append(period_high)

    # Sort: support descending (closest first), resistance ascending (closest first)
    support_levels = sorted(set(support_levels), reverse=True)
    resistance_levels = sorted(set(resistance_levels))

    return calculate_trade_levels(
        current_price=current_price,
        currency=currency,
        atr=atr,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        fair_value=fair_value,
        fair_value_source=fair_value_source,
        bb_lower=bb_lower,
        bb_upper=bb_upper,
        sma_50=sma_50,
        sma_200=sma_200,
        atr_multiplier=atr_multiplier,
    )
