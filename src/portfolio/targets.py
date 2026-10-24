"""
Target Weights

Each holding's target weight, used by `review` (Trim / Add) and later by
the rebalance proposals.

- **Equal risk contribution** (ERC): every holding contributes the same
  share of portfolio risk, using the shrunk covariance from `exposure.py`.
  Unlike inverse volatility, it accounts for correlation, so a correlated
  cluster gets less than the same names would get separately. Solved by
  cyclical coordinate descent (Griveau-Billion, Richard and Roncalli, 2013).
- **Fixed weights** take their share first: targets set in the targets file,
  holdings to Exit (0), holdings under Review or without enough history
  (their current weight, until looked into). ERC shares what's left.
- **Caps:** no position above `max_position` (or a ticker's own `max`), no
  sector above `max_sector` (funds and unknown sectors are exempt). What a
  cap removes is spread over the uncapped holdings pro rata.

The targets file (`portfolio/targets.toml`, gitignored) is optional:

    [limits]
    max_position = 0.10    # of the portfolio
    max_sector = 0.35
    cash_reserve = 0       # base currency, kept out of buys (rebalance)
    min_trade = 2000       # base currency; smaller trades are dropped (rebalance)
    max_new = 3            # new names per proposal (rebalance)

    [ticker."XYZ.DE"]      # e.g. a broad ETF
    target = 0.10          # fixed target weight
    max = 0.15             # or only a cap of its own
"""

import math
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

DEFAULT_TARGETS = Path("portfolio/targets.toml")
EXEMPT_SECTORS = ("Fund", "Unknown")

ERC_TOLERANCE = 1e-10
ERC_MAX_SWEEPS = 1000
CAP_ROUNDS = 50


@dataclass
class Limits:
    max_position: float = 0.10
    max_sector: float = 0.35
    cash_reserve: float = 0.0
    min_trade: float = 2000.0
    max_new: int = 3


@dataclass
class TickerTarget:
    target: Optional[float] = None
    max: Optional[float] = None


@dataclass
class TargetSettings:
    limits: Limits = field(default_factory=Limits)
    tickers: Dict[str, TickerTarget] = field(default_factory=dict)
    source: Optional[str] = None  # the file read, or None for the defaults


def load_targets(path: Path = DEFAULT_TARGETS) -> TargetSettings:
    """Limits and per-ticker targets from a TOML file; the defaults if it doesn't exist."""
    path = Path(path)
    if not path.exists():
        return TargetSettings()
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    unknown = set(raw) - {"limits", "ticker"}
    if unknown:
        raise ValueError(f"{path.name}: unknown section(s) {sorted(unknown)}")

    limits = Limits()
    allowed = {f.name for f in fields(Limits)}
    for key, value in (raw.get("limits") or {}).items():
        if key not in allowed:
            raise ValueError(f"{path.name}: unknown limit {key!r} (known: {sorted(allowed)})")
        setattr(limits, key, type(getattr(limits, key))(value))

    tickers: Dict[str, TickerTarget] = {}
    for ticker, values in (raw.get("ticker") or {}).items():
        bad = set(values) - {"target", "max"}
        if bad:
            raise ValueError(f"{path.name}: {ticker}: unknown key(s) {sorted(bad)}")
        tickers[ticker.upper()] = TickerTarget(
            target=_fraction(values.get("target"), f"{ticker} target"),
            max=_fraction(values.get("max"), f"{ticker} max"),
        )
    for name in ("max_position", "max_sector"):
        _fraction(getattr(limits, name), name)
    return TargetSettings(limits=limits, tickers=tickers, source=str(path))


def _fraction(value: Any, what: str) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    if not 0 <= number <= 1:
        raise ValueError(f"{what} must be a fraction between 0 and 1, got {value}")
    return number


# ==================== Equal risk contribution ====================


def equal_risk_weights(cov: pd.DataFrame) -> pd.Series:
    """
    Weights (summing to 1) at which every asset contributes the same share
    of portfolio variance.

    Cyclical coordinate descent: each weight in turn is set to the positive
    root of Σii x_i² + (Σ_j≠i Σij x_j) x_i - σ(x) / n = 0, which makes its
    risk contribution x_i (Σx)_i equal σ(x) / n. Starts from inverse
    volatility, which is the answer when assets are uncorrelated.
    """
    sigma = cov.to_numpy(dtype=float)
    n = len(sigma)
    if n == 0:
        return pd.Series(dtype=float)
    diag = np.diag(sigma)
    x = 1 / np.sqrt(diag)
    x /= x.sum()
    budget = 1.0 / n
    for _ in range(ERC_MAX_SWEEPS):
        for i in range(n):
            others = float(sigma[i] @ x - sigma[i, i] * x[i])
            vol = math.sqrt(float(x @ sigma @ x))
            x[i] = (-others + math.sqrt(others**2 + 4 * sigma[i, i] * budget * vol)) / (
                2 * sigma[i, i]
            )
        contributions = x * (sigma @ x)
        if np.max(np.abs(contributions / contributions.sum() - budget)) < ERC_TOLERANCE:
            break
    return pd.Series(x / x.sum(), index=cov.columns)


# ==================== Targets ====================


def target_weights(
    weights: Dict[str, float],
    cov: pd.DataFrame,
    sectors: Dict[str, str],
    settings: TargetSettings,
    exits: Set[str],
    frozen: Set[str],
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Target weight per holding, and notes on how they were set.

    `weights` are the current weights; `cov` covers the holdings with
    enough history; `exits` get 0; `frozen` (Review, or no history) keep
    their current weight. Returns ({ticker: target}, notes), where notes
    lists the fixed, the capped and any weight left unallocated because
    every holding hit a cap.
    """
    fixed: Dict[str, float] = {}
    for ticker, weight in weights.items():
        own = settings.tickers.get(ticker)
        if ticker in exits:
            fixed[ticker] = 0.0
        elif own and own.target is not None:
            fixed[ticker] = own.target
        elif ticker in frozen or ticker not in cov.columns:
            fixed[ticker] = weight
    free = [t for t in weights if t not in fixed]

    budget = max(0.0, 1.0 - sum(fixed.values()))
    targets = dict(fixed)
    if free:
        erc = equal_risk_weights(cov.loc[free, free])
        targets.update({t: float(erc[t]) * budget for t in free})
    capped = _apply_caps(targets, free, sectors, settings)

    notes = {
        "method": "equal risk contribution",
        "free": len(free),
        "fixed": sorted(t for t in fixed if t not in exits),
        "capped": capped,
        "unallocated": max(0.0, 1.0 - sum(targets.values())),
        "limits": {
            "max_position": settings.limits.max_position,
            "max_sector": settings.limits.max_sector,
        },
        "source": settings.source,
    }
    return targets, notes


def _apply_caps(
    targets: Dict[str, float],
    free: List[str],
    sectors: Dict[str, str],
    settings: TargetSettings,
) -> List[str]:
    """Cap positions and sectors in place, spreading the excess over the uncapped free holdings."""
    limits = settings.limits

    def position_cap(ticker: str) -> float:
        own = settings.tickers.get(ticker)
        return own.max if own and own.max is not None else limits.max_position

    capped: Set[str] = set()
    for _ in range(CAP_ROUNDS):
        excess = 0.0
        for ticker in free:
            cap = position_cap(ticker)
            if targets[ticker] > cap + 1e-12:
                excess += targets[ticker] - cap
                targets[ticker] = cap
                capped.add(ticker)
        for sector in {sectors.get(t) or "Unknown" for t in free}:
            if sector in EXEMPT_SECTORS:
                continue
            members = [t for t, s in sectors.items() if s == sector and t in targets]
            total = sum(targets[t] for t in members)
            movable = [t for t in members if t in free and targets[t] > 0]
            if total <= limits.max_sector + 1e-12 or not movable:
                continue
            over = total - limits.max_sector
            movable_total = sum(targets[t] for t in movable)
            scale = max(0.0, 1 - over / movable_total)
            for t in movable:
                excess += targets[t] * (1 - scale)
                targets[t] *= scale
                capped.add(t)
        if excess <= 1e-12:
            break
        # Spread over free holdings that are below their cap and not in a full sector
        receivers = [
            t
            for t in free
            if t not in capped
            and targets[t] < position_cap(t) - 1e-12
            and not _sector_full(t, targets, sectors, limits)
        ]
        receiving = sum(targets[t] for t in receivers)
        if not receivers or receiving <= 0:
            break  # nowhere to put it: left unallocated
        for t in receivers:
            targets[t] += excess * targets[t] / receiving
    return sorted(capped)


def _sector_full(
    ticker: str, targets: Dict[str, float], sectors: Dict[str, str], limits: Limits
) -> bool:
    sector = sectors.get(ticker) or "Unknown"
    if sector in EXEMPT_SECTORS:
        return False
    total = sum(w for t, w in targets.items() if (sectors.get(t) or "Unknown") == sector)
    return total >= limits.max_sector - 1e-12
