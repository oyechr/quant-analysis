"""
Portfolio Review

Vets every holding in a portfolio file and suggests Exit / Review / Trim /
Hold / Add for each, plus portfolio-level problems: sector and currency
concentration, and holdings that move together. The rules are explicit and
testable, like the red flags (see `decide_action`):

- Exit: a Sell or Strong Sell signal.
- Review: a high-severity red flag with a Hold or Buy signal. Red flags such
  as Altman Z or Beneish M are screening models with known false positives
  (telecoms read as distressed, acquisitions as manipulation), so for a stock
  you own they mean "look into it", not "sell". `vet` still says Pass, since
  for a new candidate there's no cost to walking away.
- Trim: the weight is well above its risk-parity target, or the holding moves
  with a larger one (daily-return correlation >= 0.80).
- Add: the vet verdict is Look deeper, the weight is below target, and it
  doesn't move with a larger holding.
- Hold: everything else.
- Check: no data (usually a wrong ticker in the map).

Funds (ETFs) have no statements, so their vet verdict means little: they are
never Exit, Review or Add, only Trim (by weight or overlap) or Hold.

Values are in one base currency (NOK by default), converted with Yahoo FX
rates. Taxes are ignored except for a note when a sale would realize a gain
outside an ASK.
"""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from ..comparison import (
    calculate_risk_parity_weights,
    identify_correlation_flags,
    return_correlations,
)
from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from ..scoring import ScoringConfig
from ..utils.concurrency import DEFAULT_WORKERS, run_concurrently
from ..utils.fx import conversion_rate, major_currency
from ..vetting.vet import LOOK_DEEPER, vet_ticker
from .nordnet import PORTFOLIO_COLUMNS

logger = logging.getLogger(__name__)

BASE_CURRENCY = "NOK"

EXIT = "Exit"
REVIEW = "Review"
TRIM = "Trim"
HOLD = "Hold"
ADD = "Add"
CHECK = "Check"
ACTION_ORDER = [EXIT, REVIEW, TRIM, ADD, CHECK, HOLD]

_SELL_SIGNALS = ("Sell", "Strong Sell")

# Trim when the weight is at least 1.5x the risk-parity target and at least
# 2 percentage points above it (so tiny positions aren't flagged over noise)
OVERWEIGHT_RATIO = 1.5
OVERWEIGHT_MIN_GAP = 0.02
# Daily-return correlation at which two holdings count as one bet
REDUNDANT_CORRELATION = 0.80
# Flag a sector holding more than this share of the portfolio
SECTOR_LIMIT = 0.35

_FUND_TYPES = ("ETF", "MUTUALFUND")
_TAXABLE_ACCOUNTS = ("AF",)
_TAX_FREE_ACCOUNTS = ("ASK", "IPS")


@dataclass
class Holding:
    """One ticker across all accounts."""

    ticker: str
    name: str
    shares: float
    cost_basis: Optional[float]  # average cost per share, in `currency`
    currency: str
    accounts: List[str] = field(default_factory=list)


@dataclass
class HoldingReview:
    holding: Holding
    action: str = CHECK
    reasons: List[str] = field(default_factory=list)
    vet: Dict[str, Any] = field(default_factory=dict)  # VetResult.to_dict()
    is_fund: bool = False
    sector: Optional[str] = None
    beta: Optional[float] = None
    price: Optional[float] = None  # listing currency
    listing_currency: Optional[str] = None
    value: Optional[float] = None  # base currency
    weight: Optional[float] = None
    target_weight: Optional[float] = None
    gain_pct: Optional[float] = None
    moves_with: Optional[Tuple[str, float]] = None  # larger holding, correlation
    error: Optional[str] = None

    @property
    def call(self) -> Optional[str]:
        return (self.vet.get("verdict") or {}).get("call")

    @property
    def signal(self) -> Optional[str]:
        return (self.vet.get("header") or {}).get("signal")

    @property
    def score(self) -> Optional[float]:
        return (self.vet.get("header") or {}).get("score")

    def to_dict(self) -> Dict[str, Any]:
        h = self.holding
        return {
            "ticker": h.ticker,
            "name": h.name,
            "accounts": h.accounts,
            "shares": h.shares,
            "cost_basis": h.cost_basis,
            "cost_currency": h.currency,
            "action": self.action,
            "reasons": self.reasons,
            "verdict": self.vet.get("verdict"),
            "signal": self.signal,
            "score": self.score,
            "is_fund": self.is_fund,
            "sector": self.sector,
            "beta": self.beta,
            "price": self.price,
            "listing_currency": self.listing_currency,
            "value": self.value,
            "weight": self.weight,
            "target_weight": self.target_weight,
            "gain_pct": self.gain_pct,
            "moves_with": (
                {"ticker": self.moves_with[0], "correlation": self.moves_with[1]}
                if self.moves_with
                else None
            ),
            "red_flags": self.vet.get("red_flags") or [],
            "signal_flips": self.vet.get("signal_flips") or {},
            "error": self.error,
        }


@dataclass
class PortfolioReview:
    holdings: List[HoldingReview]
    base_currency: str
    preset: str
    unmapped: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_currency": self.base_currency,
            "preset": self.preset,
            "summary": self.summary,
            "holdings": [r.to_dict() for r in sort_reviews(self.holdings)],
            "unmapped": self.unmapped,
        }


# ==================== Input ====================


def load_portfolio(path: Path) -> Tuple[List[Holding], List[str]]:
    """
    Holdings from a portfolio file (see `quant import-portfolio`), one per
    ticker across accounts, plus the names that have no ticker.

    Shares are summed and the cost basis is share-weighted over the rows that
    have one.
    """
    frame = pd.read_csv(path, dtype={"ticker": str, "account": str, "name": str})
    missing = [c for c in ("ticker", "shares") if c not in frame.columns]
    if missing:
        raise ValueError(f"{Path(path).name}: missing column(s) {missing}")
    for column in PORTFOLIO_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame["ticker"] = frame["ticker"].fillna("").str.strip().str.upper()
    frame["name"] = frame["name"].fillna("").astype(str)
    frame["account"] = frame["account"].fillna("").astype(str)
    frame["shares"] = pd.to_numeric(frame["shares"], errors="coerce")
    frame["cost_basis"] = pd.to_numeric(frame["cost_basis"], errors="coerce")

    unmapped = sorted({n or "?" for n in frame.loc[frame["ticker"] == "", "name"]})
    holdings: List[Holding] = []
    for ticker, rows in frame[frame["ticker"] != ""].groupby("ticker", sort=False):
        rows = rows[rows["shares"] > 0]
        if rows.empty:
            continue
        shares = float(rows["shares"].sum())
        costed = rows.dropna(subset=["cost_basis"])
        cost = (
            float((costed["shares"] * costed["cost_basis"]).sum() / costed["shares"].sum())
            if not costed.empty and costed["shares"].sum() > 0
            else None
        )
        currency = next((str(c) for c in rows["currency"] if isinstance(c, str) and c), "")
        holdings.append(
            Holding(
                ticker=str(ticker),
                name=str(rows["name"].iloc[0]),
                shares=shares,
                cost_basis=cost,
                currency=currency,
                accounts=list(dict.fromkeys(a for a in rows["account"] if a)),
            )
        )
    return holdings, unmapped


# ==================== Review ====================


def review_portfolio(
    holdings: List[Holding],
    fetcher: Optional[DataFetcher] = None,
    options: Optional[AnalysisOptions] = None,
    base_currency: str = BASE_CURRENCY,
    workers: int = DEFAULT_WORKERS,
    data_dir: str = "data",
    progress: Optional[Callable[[str, Optional[Exception]], None]] = None,
) -> PortfolioReview:
    """Vet every holding, value it in the base currency and decide an action."""
    fetcher = fetcher or DataFetcher(cache_dir=data_dir)
    options = options or AnalysisOptions(include_context=False)
    config = options.scoring_config or ScoringConfig()
    use_cache = options.use_cache
    by_ticker = {h.ticker: h for h in holdings}
    reviews: Dict[str, HoldingReview] = {h.ticker: HoldingReview(holding=h) for h in holdings}

    def vet(ticker: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        result = vet_ticker(ticker, fetcher=fetcher, options=options, data_dir=data_dir)
        return result.to_dict(), result.report.get("info") or {}

    for ticker, outcome, error in run_concurrently(vet, list(by_ticker), workers=workers):
        review = reviews[ticker]
        if error is not None or outcome is None:
            review.error = str(error or "no result")
        else:
            data, info = outcome
            review.vet = data
            review.is_fund = is_fund(info, by_ticker[ticker].name)
            review.sector = "Fund" if review.is_fund else _clean(info.get("sector"))
            review.beta = _num(info.get("beta"))
            review.price = _num((data.get("header") or {}).get("price"))
            review.listing_currency = info.get("currency") or by_ticker[ticker].currency
        if progress:
            progress(ticker, error)

    def fx_lookup(symbol: str) -> Optional[float]:
        return fetcher.latest_close(symbol, use_cache=use_cache)

    rates: Dict[Tuple[str, str], Optional[float]] = {}

    def rate(from_ccy: str, to_ccy: str) -> Optional[float]:
        key = (from_ccy, to_ccy)
        if key not in rates:
            converted = conversion_rate(from_ccy, to_ccy, fx_lookup)
            rates[key] = converted[0] if converted else None
        return rates[key]

    for review in reviews.values():
        value_holding(review, base_currency, rate)
    total = sum(r.value for r in reviews.values() if r.value)
    for review in reviews.values():
        if review.value and total:
            review.weight = review.value / total

    prices = _price_history(fetcher, [t for t, r in reviews.items() if r.vet], use_cache)
    parity = calculate_risk_parity_weights(prices) or {}
    for ticker, weight in (parity.get("weights") or {}).items():
        reviews[ticker].target_weight = weight
    correlations = return_correlations(prices, pairwise=True)
    _find_overlaps(list(reviews.values()), correlations)

    for review in reviews.values():
        review.action, review.reasons = decide_action(review)

    return PortfolioReview(
        holdings=list(reviews.values()),
        base_currency=base_currency,
        preset=config.name,
        summary=summarize_portfolio(list(reviews.values()), correlations, base_currency),
    )


def is_fund(info: Dict[str, Any], name: str = "") -> bool:
    """ETFs and mutual funds: by Yahoo's quote type, else by the name."""
    quote_type = str(info.get("quote_type") or "").upper()
    if quote_type:
        return quote_type in _FUND_TYPES
    return any(word in name.upper().split() for word in ("ETF", "UCITS"))


def value_holding(
    review: HoldingReview,
    base_currency: str,
    rate: Callable[[str, str], Optional[float]],
) -> None:
    """Market value in the base currency, and gain vs cost in the cost currency."""
    h = review.holding
    if review.price is None or not review.listing_currency:
        return
    to_base = rate(review.listing_currency, base_currency)
    if to_base is not None:
        review.value = h.shares * review.price * to_base
    if h.cost_basis and h.cost_basis > 0 and h.currency:
        to_cost = rate(review.listing_currency, h.currency)
        if to_cost is not None:
            review.gain_pct = (review.price * to_cost / h.cost_basis - 1) * 100


def _price_history(
    fetcher: DataFetcher, tickers: List[str], use_cache: bool
) -> Dict[str, pd.DataFrame]:
    """One year of daily prices per ticker (already cached by the vet run)."""
    prices: Dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            frame = fetcher.fetch_ticker(ticker, period="1y", use_cache=use_cache)
        except Exception as e:
            logger.warning(f"No price history for {ticker}: {e}")
            continue
        if frame is not None and not frame.empty and "Close" in frame.columns:
            prices[ticker] = frame
    return prices


def _find_overlaps(reviews: List[HoldingReview], correlations: pd.DataFrame) -> None:
    """For each holding, the most correlated larger holding at or above the threshold."""
    if correlations.empty:
        return
    for review in reviews:
        ticker = review.holding.ticker
        if review.value is None or ticker not in correlations.columns:
            continue
        best: Optional[Tuple[str, float]] = None
        for other in reviews:
            other_ticker = other.holding.ticker
            if (
                other is review
                or other.value is None
                or other.value <= review.value
                or other_ticker not in correlations.columns
            ):
                continue
            corr = float(correlations.loc[ticker, other_ticker])
            if (
                math.isfinite(corr)
                and corr >= REDUNDANT_CORRELATION
                and (best is None or corr > best[1])
            ):
                best = (other_ticker, corr)
        review.moves_with = best


def is_overweight(weight: Optional[float], target: Optional[float]) -> bool:
    if weight is None or target is None:
        return False
    return weight >= target * OVERWEIGHT_RATIO and weight - target >= OVERWEIGHT_MIN_GAP


def decide_action(review: HoldingReview) -> Tuple[str, List[str]]:
    """The action for one holding and its reasons, most decisive first."""
    if not review.vet or review.price is None or review.score is None:
        detail = review.error or ("no price" if review.vet else "no score")
        return CHECK, [f"no data ({detail}); check the ticker in portfolio/tickers.csv"]

    # The verdict itself is shown next to the action, so reasons say why.
    # Verdict reasons start with the signal ("Sell 44/100 ...") and include
    # "red flag: ..." for the first high-severity flag.
    verdict_reasons: List[str] = list((review.vet.get("verdict") or {}).get("reasons") or [])
    weight, target = review.weight, review.target_weight
    call = review.call
    high_flags = [
        f["title"] for f in review.vet.get("red_flags") or [] if f.get("severity") == "high"
    ]

    if not review.is_fund and review.signal in _SELL_SIGNALS:
        return EXIT, _with_tax_note(review, verdict_reasons[:2])

    if not review.is_fund and high_flags:
        return REVIEW, [
            *(f"red flag: {title.lower()}" for title in high_flags),
            f"{verdict_reasons[0]}; look into the flag before selling"
            if verdict_reasons
            else "look into the flag before selling",
        ]

    trims: List[str] = []
    if is_overweight(weight, target):
        trims.append(f"weight {_weights(weight, target)}")
    if review.moves_with:
        other, corr = review.moves_with
        trims.append(f"moves with {other}, a larger holding (correlation {corr:.2f})")
    if trims:
        return TRIM, _with_tax_note(review, trims)

    if review.is_fund:
        return HOLD, ["fund: judged on weight and overlap only"]
    if call == LOOK_DEEPER:
        if weight is not None and target is not None and weight < target:
            return ADD, [f"weight {_weights(weight, target)}", *verdict_reasons[:1]]
        return HOLD, ["Look deeper, but already at or above target weight", *verdict_reasons[:1]]
    return HOLD, verdict_reasons[:2] or [f"vet verdict {call}"]


def _weights(weight: Optional[float], target: Optional[float]) -> str:
    return f"{weight or 0.0:.1%} vs risk-parity target {target or 0.0:.1%}"


def _with_tax_note(review: HoldingReview, reasons: List[str]) -> List[str]:
    """Selling at a gain outside a tax-free account realizes it."""
    accounts = [a.upper() for a in review.holding.accounts]
    if not review.gain_pct or review.gain_pct <= 0:
        return reasons
    if any(a in _TAX_FREE_ACCOUNTS for a in accounts) and len(accounts) > 1:
        return [*reasons, "sell from the ASK first: a sale in AF realizes the gain"]
    if any(a in _TAXABLE_ACCOUNTS for a in accounts):
        return [*reasons, f"selling realizes a {review.gain_pct:.0f}% gain in AF"]
    return reasons


# ==================== Portfolio level ====================


def summarize_portfolio(
    reviews: List[HoldingReview], correlations: pd.DataFrame, base_currency: str
) -> Dict[str, Any]:
    valued = [r for r in reviews if r.value is not None and r.weight is not None]
    total = sum(r.value or 0.0 for r in valued)

    def weighted(attr: Callable[[HoldingReview], Optional[float]]) -> Optional[float]:
        pairs = [(r.weight or 0.0, attr(r)) for r in valued if attr(r) is not None]
        weight_sum = sum(w for w, _ in pairs)
        if not pairs or weight_sum <= 0:
            return None
        return sum(w * (v or 0.0) for w, v in pairs) / weight_sum

    by_sector = _shares(valued, lambda r: r.sector or "Unknown")
    by_currency = _shares(valued, lambda r: major_currency(r.listing_currency or "?")[0])
    flags = [
        f"{row['name']} is {row['weight']:.0%} of the portfolio (limit {SECTOR_LIMIT:.0%})"
        for row in by_sector
        if row["weight"] > SECTOR_LIMIT and row["name"] not in ("Unknown", "Fund")
    ]
    largest = max(valued, key=lambda r: r.value or 0.0, default=None)

    diversification = identify_correlation_flags(correlations, REDUNDANT_CORRELATION)
    pairs = sorted(
        diversification.get("redundant_pairs") or [],
        key=lambda p: p["correlation"],
        reverse=True,
    )
    actions = {a: sum(1 for r in reviews if r.action == a) for a in ACTION_ORDER}

    return {
        "total_value": total,
        "base_currency": base_currency,
        "holdings": len(reviews),
        "valued": len(valued),
        "actions": {a: n for a, n in actions.items() if n},
        "weighted_score": _round(weighted(lambda r: r.score), 1),
        "weighted_beta": _round(weighted(lambda r: r.beta), 2),
        "gain_pct": _round(_portfolio_gain(valued, total), 1),
        "largest": (
            {"ticker": largest.holding.ticker, "weight": largest.weight} if largest else None
        ),
        "by_sector": by_sector,
        "by_currency": by_currency,
        "concentration_flags": flags,
        "correlated_pairs": [
            {"pair": list(p["pair"]), "correlation": p["correlation"]} for p in pairs
        ],
        "diversification_score": diversification.get("diversification_score"),
        "average_correlation": diversification.get("average_correlation"),
    }


def _shares(
    reviews: List[HoldingReview], key: Callable[[HoldingReview], str]
) -> List[Dict[str, Any]]:
    """Weight per group, largest first."""
    totals: Dict[str, float] = {}
    for r in reviews:
        totals[key(r)] = totals.get(key(r), 0.0) + (r.weight or 0.0)
    return [
        {"name": name, "weight": weight}
        for name, weight in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]


def _portfolio_gain(valued: List[HoldingReview], total: float) -> Optional[float]:
    """Value-weighted gain, from each holding's gain (cost = value / (1 + gain))."""
    with_gain = [r for r in valued if r.gain_pct is not None and r.value]
    if not with_gain:
        return None
    value = sum(r.value or 0.0 for r in with_gain)
    cost = sum((r.value or 0.0) / (1 + (r.gain_pct or 0.0) / 100) for r in with_gain)
    return (value / cost - 1) * 100 if cost > 0 else None


def sort_reviews(reviews: List[HoldingReview]) -> List[HoldingReview]:
    """By action (Exit first), then by weight, largest first."""
    return sorted(reviews, key=lambda r: (ACTION_ORDER.index(r.action), -(r.weight or 0.0)))


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return None if not text or text == "N/A" else text


def _num(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return result if math.isfinite(result) else None


def _round(value: Optional[float], digits: int) -> Optional[float]:
    return round(value, digits) if value is not None else None
