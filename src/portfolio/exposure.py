"""
Portfolio Exposure

What the portfolio as a whole is exposed to, as seen from the base currency
(NOK by default): volatility and each holding's share of the risk, beta
against the home market and the world, concentration, value and risk by
sector, country and currency, and the factor tilts of the stocks held.

- **Returns** are weekly, in the base currency, over two years. Each listing's
  closes are converted with the daily FX rate (a NOK investor bears the
  currency risk). Weekly rather than daily, because Oslo, Europe and New York
  close at different times and daily returns understate how much they move
  together.
- **Covariance** is shrunk towards a constant-correlation target (Ledoit and
  Wolf, "Honey, I Shrunk the Sample Covariance Matrix", 2004): with about 40
  holdings and 100 weeks the sample matrix is noisy.
- **Risk contribution** of a holding is w_i (Σw)_i / w'Σw; they sum to 100%.
- **Factor tilts** are holdings-based: the weighted median of each stock's
  earnings yield (value), ROE (quality), 12-1 month return (momentum) and
  volatility, plus the weighted vet dimension scores (50 is neutral). They
  describe the portfolio; they are not regression loadings.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..discovery.factor_ranking import momentum_12_1
from ..utils.financial import trading_dates
from ..utils.fx import fx_symbol, major_currency

if TYPE_CHECKING:
    from .review import HoldingReview

logger = logging.getLogger(__name__)

HISTORY_PERIOD = "2y"
WEEKS_PER_YEAR = 52
# A holding needs three quarters of the two years to be in the risk numbers.
# The window is the weeks every included holding covers, so a lower bar lets
# one recent listing cut everyone's history short.
MIN_WEEKS = 78

# (symbol, listing currency, label)
WORLD_BENCHMARK = ("ACWI", "USD", "World")
HOME_BENCHMARKS: Dict[str, Tuple[str, str, str]] = {"NOK": ("OSEBX.OL", "NOK", "Oslo")}

DIMENSIONS = ("valuation", "fundamental", "technical", "risk")


@dataclass
class Exposure:
    summary: Dict[str, Any]  # JSON-ready, shown by `review`
    covariance: pd.DataFrame = field(default_factory=pd.DataFrame)  # weekly, shrunk
    correlations: pd.DataFrame = field(default_factory=pd.DataFrame)  # weekly, sample


# ==================== Returns and covariance ====================


def to_base_currency(
    close: pd.Series,
    currency: str,
    base_currency: str,
    fx_closes: Callable[[str], Optional[pd.Series]],
) -> Optional[pd.Series]:
    """
    Daily closes in the base currency, indexed by trading date.

    Minor units (GBp) are turned into the major currency first. The FX rate
    is carried forward over days the currency market has no bar. None when
    the FX series is unavailable.
    """
    major, units = major_currency(currency)
    local = _by_trading_date(close) / units
    if major == base_currency.upper():
        return local
    fx = fx_closes(fx_symbol(major, base_currency))
    if fx is None or fx.dropna().empty:
        return None
    rate = _by_trading_date(fx)
    rate = rate.reindex(local.index.union(rate.index)).ffill().reindex(local.index)
    return (local * rate).dropna()


def weekly_returns(closes: Dict[str, pd.Series], min_weeks: int = MIN_WEEKS) -> pd.DataFrame:
    """
    Friday-to-Friday returns over the weeks every series covers.

    Each series is carried forward over its own market's holidays. Series
    with fewer than `min_weeks` returns are left out, so a recent listing
    doesn't cut everyone's history short.
    """
    if not closes:
        return pd.DataFrame()
    frame = pd.DataFrame(closes).sort_index().ffill()
    returns = frame.resample("W-FRI").last().pct_change(fill_method=None).iloc[1:]
    enough = [c for c in returns.columns if returns[c].notna().sum() >= min_weeks]
    return returns[enough].dropna()


def shrunk_covariance(returns: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
    """
    Ledoit-Wolf covariance shrunk towards constant correlation, and the
    shrinkage intensity (0 = the sample matrix, 1 = the target).

    The target keeps every variance and sets each correlation to the
    average one. Same estimator as Ledoit and Wolf's covCor.m (per period,
    not annualized).
    """
    x = returns.to_numpy(dtype=float)
    t, n = x.shape
    x = x - x.mean(axis=0)
    sample = x.T @ x / t
    if n < 2:
        return pd.DataFrame(sample, index=returns.columns, columns=returns.columns), 0.0

    var = np.diag(sample)
    sd = np.sqrt(var)
    r_bar = (np.sum(sample / np.outer(sd, sd)) - n) / (n * (n - 1))
    prior = r_bar * np.outer(sd, sd)
    np.fill_diagonal(prior, var)

    # pi: sum of the asymptotic variances of the sample covariances
    pi_mat = (x**2).T @ (x**2) / t - sample**2
    pi_hat = float(pi_mat.sum())
    # rho: sum of the asymptotic covariances of target and sample entries
    theta = (x**3).T @ x / t - var[:, None] * sample
    np.fill_diagonal(theta, 0.0)
    rho_hat = float(np.trace(pi_mat) + r_bar * np.sum(np.outer(1 / sd, sd) * theta))
    gamma_hat = float(np.sum((sample - prior) ** 2))

    shrinkage = 0.0
    if gamma_hat > 0:
        shrinkage = max(0.0, min(1.0, (pi_hat - rho_hat) / gamma_hat / t))
    shrunk = shrinkage * prior + (1 - shrinkage) * sample
    return pd.DataFrame(shrunk, index=returns.columns, columns=returns.columns), shrinkage


def risk_contributions(weights: pd.Series, cov: pd.DataFrame) -> pd.Series:
    """Each holding's share of portfolio variance, w_i (Σw)_i / w'Σw (sums to 1)."""
    w = weights.reindex(cov.columns).fillna(0.0)
    marginal = cov.to_numpy() @ w.to_numpy()
    total = float(w.to_numpy() @ marginal)
    if not total > 0:
        return pd.Series(np.nan, index=cov.columns)
    return pd.Series(w.to_numpy() * marginal / total, index=cov.columns)


def beta(returns: pd.Series, benchmark: pd.Series, min_weeks: int = MIN_WEEKS) -> Optional[float]:
    """Cov(r, b) / Var(b) over the weeks both have, or None with too few."""
    both = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if len(both) < min_weeks:
        return None
    variance = float(both.iloc[:, 1].var())
    if not variance > 0:
        return None
    return float(both.iloc[:, 0].cov(both.iloc[:, 1])) / variance


def effective_number(shares: List[float]) -> Optional[float]:
    """1 / Σs² of shares normalized to sum to 1 (N for N equal shares)."""
    total = sum(shares)
    if not shares or not total > 0:
        return None
    return 1.0 / sum((s / total) ** 2 for s in shares)


def weighted_median(values: List[Tuple[float, float]]) -> Optional[float]:
    """Median of (weight, value) pairs: the value where the cumulative weight reaches half."""
    pairs = sorted((v, w) for w, v in values if w > 0)
    total = sum(w for _, w in pairs)
    if not pairs:
        return None
    running = 0.0
    for value, w in pairs:
        running += w
        if running >= total / 2:
            return value
    return pairs[-1][0]


# ==================== Exposure ====================


def measure_exposure(
    reviews: List["HoldingReview"],
    closes: Dict[str, pd.Series],
    benchmarks: Dict[str, pd.Series],
    local_closes: Optional[Dict[str, pd.Series]] = None,
) -> Exposure:
    """
    Portfolio exposure from the holdings' weights and base-currency closes.

    `closes` and `benchmarks` (label -> closes) are daily, in the base
    currency. `local_closes` (listing currency) feed the momentum tilt.
    Holdings without enough history are listed under "excluded" and left
    out of the risk numbers (weights renormalized over the rest). Sets each
    review's `beta` (against the world benchmark) and `risk_share`.

    The covariance (shrunk) and correlations (sample) cover the included
    holdings, from the same weekly returns.
    """
    valued = [r for r in reviews if r.weight]
    weights = pd.Series({r.holding.ticker: r.weight or 0.0 for r in valued}, dtype=float)
    returns = weekly_returns({t: closes[t] for t in weights.index if t in closes})
    included = [t for t in weights.index if t in returns.columns]
    excluded = [t for t in weights.index if t not in returns.columns]

    result: Dict[str, Any] = {
        "weeks": len(returns),
        "start": returns.index[0].date().isoformat() if len(returns) else None,
        "end": returns.index[-1].date().isoformat() if len(returns) else None,
        "coverage": float(weights[included].sum()) if included else 0.0,
        "excluded": excluded,
        "volatility": None,
        "shrinkage": None,
        "betas": [],
    }
    risk = pd.Series(dtype=float)
    vols: Dict[str, float] = {}
    cov = pd.DataFrame()
    if included:
        cov, shrinkage = shrunk_covariance(returns[included])
        w = weights[included] / weights[included].sum()
        risk = risk_contributions(w, cov)
        variance = float(w.to_numpy() @ cov.to_numpy() @ w.to_numpy())
        result["volatility"] = math.sqrt(variance * WEEKS_PER_YEAR)
        result["shrinkage"] = shrinkage
        vols = {t: math.sqrt(float(cov.loc[t, t]) * WEEKS_PER_YEAR) for t in included}

        portfolio = returns[included] @ w
        bench_returns = {
            label: series.resample("W-FRI").last().pct_change(fill_method=None)
            for label, series in benchmarks.items()
        }
        for label, bench in bench_returns.items():
            result["betas"].append({"benchmark": label, "beta": beta(portfolio, bench)})
        world = bench_returns.get(WORLD_BENCHMARK[2])
        for r in valued:
            ticker = r.holding.ticker
            if ticker in risk.index:
                r.risk_share = float(risk[ticker])
            if world is not None and ticker in returns.columns:
                r.beta = beta(returns[ticker], world)

    weight_list = sorted((float(v) for v in weights), reverse=True)
    result.update(
        {
            "top5": sum(weight_list[:5]),
            "top10": sum(weight_list[:10]),
            "effective_positions": effective_number(weight_list),
            "effective_risk_positions": effective_number([float(v) for v in risk.dropna()]),
            "by_sector": _groups(valued, risk, lambda r: r.sector or "Unknown"),
            "by_country": _groups(
                valued, risk, lambda r: "Fund" if r.is_fund else (r.country or "Unknown")
            ),
            "by_currency": _groups(
                valued, risk, lambda r: major_currency(r.listing_currency or "?")[0]
            ),
            "factors": _factor_tilts(valued, vols, local_closes or {}),
            "dimensions": _dimension_scores(valued),
        }
    )
    correlations = returns[included].corr() if len(included) >= 2 else pd.DataFrame()
    return Exposure(summary=result, covariance=cov, correlations=correlations)


def _by_trading_date(series: pd.Series) -> pd.Series:
    out = series.dropna().copy()
    out.index = trading_dates(pd.DatetimeIndex(out.index))
    return out[~out.index.duplicated(keep="last")].sort_index()


def _groups(
    reviews: List["HoldingReview"],
    risk: pd.Series,
    key: Callable[["HoldingReview"], str],
) -> List[Dict[str, Any]]:
    """Value weight and risk share per group, largest weight first."""
    totals: Dict[str, Dict[str, Optional[float]]] = {}
    for r in reviews:
        group = totals.setdefault(key(r), {"weight": 0.0, "risk": None})
        group["weight"] = (group["weight"] or 0.0) + (r.weight or 0.0)
        share = risk.get(r.holding.ticker)
        if share is not None and math.isfinite(share):
            group["risk"] = (group["risk"] or 0.0) + float(share)
    return [
        {"name": name, **values}
        for name, values in sorted(
            totals.items(), key=lambda kv: kv[1]["weight"] or 0.0, reverse=True
        )
    ]


def _factor_tilts(
    reviews: List["HoldingReview"],
    vols: Dict[str, float],
    local_closes: Dict[str, pd.Series],
) -> List[Dict[str, Any]]:
    """Weighted median per factor over the stocks (funds left out), with the extremes."""
    stocks = [r for r in reviews if not r.is_fund]
    stock_weight = sum(r.weight or 0.0 for r in stocks)

    def measure(r: "HoldingReview", name: str) -> Optional[float]:
        ticker = r.holding.ticker
        if name == "momentum":
            close = local_closes.get(ticker)
            return momentum_12_1(close.dropna()) if close is not None else None
        if name == "volatility":
            return vols.get(ticker)
        return r.characteristics.get(name)

    tilts = []
    for factor, name in (
        ("Value", "earnings_yield"),
        ("Quality", "roe"),
        ("Momentum", "momentum"),
        ("Low volatility", "volatility"),
    ):
        values = [(r, measure(r, name)) for r in stocks]
        known = [(r, v) for r, v in values if v is not None and math.isfinite(v)]
        if not known:
            continue
        known.sort(key=lambda rv: rv[1])
        tilts.append(
            {
                "factor": factor,
                "measure": name,
                "median": weighted_median([(r.weight or 0.0, v) for r, v in known]),
                "coverage": (
                    sum(r.weight or 0.0 for r, _ in known) / stock_weight if stock_weight else 0.0
                ),
                "low": {"ticker": known[0][0].holding.ticker, "value": known[0][1]},
                "high": {"ticker": known[-1][0].holding.ticker, "value": known[-1][1]},
            }
        )
    return tilts


def _dimension_scores(reviews: List["HoldingReview"]) -> Dict[str, Optional[float]]:
    """Weighted average vet dimension score over the stocks (50 is neutral)."""
    stocks = [r for r in reviews if not r.is_fund]
    scores: Dict[str, Optional[float]] = {}
    for name in DIMENSIONS:
        pairs = [
            (r.weight or 0.0, float(score))
            for r in stocks
            if (score := ((r.vet.get("header") or {}).get("dimensions") or {}).get(name))
            is not None
        ]
        total = sum(w for w, _ in pairs)
        scores[name] = sum(w * s for w, s in pairs) / total if total > 0 else None
    return scores
