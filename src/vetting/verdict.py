"""
What Would Change the Verdict

- Fair value range: Monte Carlo percentiles, DCF and DDM per-share values.
- Signal flip prices: the price at which the composite signal would move one
  band up (e.g. Hold -> Buy) or down, holding everything except price-driven
  valuation inputs constant.
"""

import copy
import math
from typing import Any, Callable, Dict, List, Optional

from ..scoring import ScoringConfig, StockScorer

SIGNAL_BANDS: List[str] = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"]

# Search range for flip prices, as multiples of the current price
_MIN_FACTOR = 0.2
_MAX_FACTOR = 5.0
_ITERATIONS = 40

# Price multiples in info that move one-for-one with price
_PRICE_MULTIPLES = (
    "pe_ratio",
    "forward_pe",
    "peg_ratio",
    "price_to_book",
    "price_to_sales",
    "ev_to_ebitda",
    "current_price",
    "market_cap",
)


def fair_value_range(report: Dict[str, Any]) -> Dict[str, Any]:
    """Collect model-implied values per share next to the current price."""
    info = report.get("info") or {}
    valuation = report.get("valuation_analysis") or {}
    price = current_price(report)
    result: Dict[str, Any] = {
        "current_price": price,
        "currency": info.get("currency"),
        "currency_note": _currency_note(report),
    }

    mc = valuation.get("monte_carlo_valuation") or {}
    intervals = mc.get("confidence_intervals") or {}
    if intervals and not mc.get("error"):
        result["monte_carlo"] = {
            **{k: _num(v) for k, v in intervals.items()},
            "probability_undervalued": _num(mc.get("probability_undervalued")),
        }

    analysts = analyst_targets(info)
    if analysts:
        result["analysts"] = analysts

    for key, name in (("dcf_valuation", "dcf"), ("ddm_valuation", "ddm")):
        model = valuation.get(key) or {}
        value = _num(model.get("intrinsic_value_per_share"))
        if value is not None and not model.get("error"):
            result[name] = value

    dcf = valuation.get("dcf_valuation") or {}
    if not dcf.get("error") and dcf.get("growth_rate_used") is not None:
        # The reverse DCF reads better than a bare value: "the price implies X% growth"
        result["dcf_assumptions"] = {
            "growth_start": _num(dcf.get("growth_rate_used")),
            "implied_growth": _num(dcf.get("implied_growth_pct")),
            "terminal_growth": _num(dcf.get("terminal_growth_rate")),
            "wacc": _num(dcf.get("wacc_used")),
            "years": dcf.get("projection_years"),
        }

    if price:
        result["upside_pct"] = {
            name: (value / price - 1) * 100
            for name, value in (
                ("analyst_mean", (result.get("analysts") or {}).get("mean")),
                ("mc_median", (result.get("monte_carlo") or {}).get("ci_50")),
                ("dcf", result.get("dcf")),
                ("ddm", result.get("ddm")),
            )
            if value is not None and value > 0
        }
    return result


def analyst_targets(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Yahoo's analyst price-target consensus (listing currency), if any."""
    mean = _num(info.get("target_mean_price"))
    if mean is None or mean <= 0:
        return None
    return {
        "mean": mean,
        "median": _num(info.get("target_median_price")),
        "low": _num(info.get("target_low_price")),
        "high": _num(info.get("target_high_price")),
        "count": info.get("analyst_count"),
        "recommendation_mean": _num(info.get("recommendation_mean")),
        "recommendation": info.get("recommendation_key"),
    }


def reprice_report(report: Dict[str, Any], factor: float) -> Dict[str, Any]:
    """
    A copy of the report as if the price were `factor` times today's.

    Only price-driven valuation inputs move: multiples, DCF premium, and FCF
    yield. Technical and risk data stay as they are.
    """
    repriced = dict(report)
    info = dict(report.get("info") or {})
    for key in _PRICE_MULTIPLES:
        value = _num(info.get(key))
        if value is not None:
            info[key] = value * factor
    repriced["info"] = info

    valuation = copy.deepcopy(report.get("valuation_analysis") or {})
    dcf = valuation.get("dcf_valuation") or {}
    premium = _num(dcf.get("discount_premium_pct"))
    if premium is not None:
        dcf["discount_premium_pct"] = ((1 + premium / 100) * factor - 1) * 100
    fcf_metrics = valuation.get("fcf_metrics") or {}
    if _num(fcf_metrics.get("fcf_yield")) is not None:
        fcf_metrics["fcf_yield"] = fcf_metrics["fcf_yield"] / factor
    repriced["valuation_analysis"] = valuation
    return repriced


def signal_flip_prices(
    report: Dict[str, Any], config: Optional[ScoringConfig] = None
) -> Dict[str, Any]:
    """
    Price at which the composite signal moves one band up and one band down.

    Valuation sub-scores only get better as price falls, so the signal is
    monotonic in price and a bisection finds each boundary.
    """
    price = current_price(report)
    scorer = StockScorer(config=config)
    if not price or not report.get("valuation_analysis"):
        return {}

    def band(factor: float) -> int:
        repriced = reprice_report(report, factor)
        result = scorer.score_from_analyses(
            technical_data=repriced.get("technical_analysis"),
            fundamental_data=repriced.get("fundamental_analysis"),
            risk_data=repriced.get("risk_analysis"),
            valuation_data=repriced.get("valuation_analysis"),
            ticker_info=repriced.get("info"),
            ticker=repriced.get("ticker", "UNKNOWN"),
            peer_valuation=repriced.get("peer_valuation"),
        )
        return SIGNAL_BANDS.index(result.signal)

    current = band(1.0)
    flips: Dict[str, Any] = {"current_signal": SIGNAL_BANDS[current], "current_price": price}

    if current < len(SIGNAL_BANDS) - 1:
        flips["up"] = _search(band, current + 1, price, going_up=True)
    if current > 0:
        flips["down"] = _search(band, current - 1, price, going_up=False)
    return flips


def _search(
    band: Callable[[float], int], target: int, price: float, going_up: bool
) -> Dict[str, Any]:
    """Bisect for the factor where the band first reaches `target`."""
    signal = SIGNAL_BANDS[target]
    if going_up:
        # Cheaper -> better band. reached(lo) should hold, reached(hi=1) doesn't.
        lo, hi = _MIN_FACTOR, 1.0
        if band(lo) < target:
            return {"signal": signal, "price": None, "note": _out_of_range(lo)}
    else:
        lo, hi = 1.0, _MAX_FACTOR
        if band(hi) > target:
            return {"signal": signal, "price": None, "note": _out_of_range(hi)}

    for _ in range(_ITERATIONS):
        mid = (lo + hi) / 2
        reached = band(mid) >= target if going_up else band(mid) <= target
        if going_up:
            lo, hi = (mid, hi) if reached else (lo, mid)
        else:
            lo, hi = (lo, mid) if reached else (mid, hi)
    factor = lo if going_up else hi
    return {
        "signal": signal,
        "price": price * factor,
        "change_pct": (factor - 1) * 100,
    }


def _out_of_range(factor: float) -> str:
    return f"not reached by valuation alone within {(factor - 1) * 100:+.0f}%"


def current_price(report: Dict[str, Any]) -> Optional[float]:
    info = report.get("info") or {}
    for value in (
        info.get("current_price"),
        ((report.get("technical_analysis") or {}).get("latest_values") or {}).get("close_price"),
        ((report.get("price_data") or {}).get("latest") or {}).get("close"),
    ):
        price = _num(value)
        if price and price > 0:
            return price
    return None


def _currency_note(report: Dict[str, Any]) -> Optional[str]:
    """How statement values relate to the price currency, when they differ."""
    info = report.get("info") or {}
    listing, statements = info.get("currency"), info.get("financial_currency")
    if not listing or not statements or listing == statements:
        return None
    conversion = report.get("currency_conversion") or {}
    rate = conversion.get("rate")
    if rate is not None:
        return f"Statements converted {statements} -> {listing} at {rate:.4g}"
    return f"Caution: statements in {statements}, price in {listing}, not converted"


def _num(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return None if math.isnan(result) or math.isinf(result) else result
