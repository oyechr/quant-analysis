"""
Backtest Statistics

Each statistic is computed across tickers within a month first, then
averaged over months, so every month counts once however many tickers it
has. Confidence intervals use Newey-West standard errors with h-1 lags for an
h-month horizon, because monthly samples of 3- and 6-month returns overlap
(consecutive months share most of their window).

- Rank IC: Spearman correlation between the signal and the forward return.
  Above about 0.03 is typical for a useful equity signal.
- Quintile spread: mean forward return of the top fifth minus the bottom fifth.
- Hit rate: the share of months in which the top fifth beat the bottom fifth.
- Signal bands: mean forward return and the share beating the benchmark for
  each Buy/Hold/Sell band of the price-only composite. Useful bands rise from
  Strong Sell to Strong Buy.
"""

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..scoring.config import SignalThresholds
from .engine import SIGNALS

MIN_CROSS_SECTION = 10  # tickers needed in a month for an IC or quintiles
QUANTILES = 5
Z_95 = 1.96
BANDS = ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")


def newey_west_se(values: np.ndarray, lags: int) -> float:
    """Standard error of the mean, robust to autocorrelation up to `lags` (Bartlett weights)."""
    n = len(values)
    if n < 2:
        return math.nan
    x = values - values.mean()
    variance = float(x @ x) / n
    for k in range(1, min(lags, n - 1) + 1):
        variance += 2 * (1 - k / (lags + 1)) * float(x[k:] @ x[:-k]) / n
    return math.sqrt(max(variance, 0.0) / n)


def mean_ci(series: pd.Series, lags: int = 0) -> Optional[Dict[str, Any]]:
    """Mean with a 95% confidence interval; None with fewer than two values."""
    values = series.dropna().to_numpy(dtype=float)
    if len(values) < 2:
        return None
    mean = float(values.mean())
    se = newey_west_se(values, lags)
    return {
        "mean": mean,
        "low": mean - Z_95 * se,
        "high": mean + Z_95 * se,
        "t": mean / se if se > 0 else None,
        "n": len(values),
    }


def monthly_ic(obs: pd.DataFrame, signal: str, returns: str) -> pd.Series:
    """Spearman correlation of signal and forward return, per month."""

    def ic(group: pd.DataFrame) -> float:
        group = group.dropna()
        if len(group) < MIN_CROSS_SECTION or group[signal].nunique() < 2:
            return math.nan
        return float(group[signal].rank().corr(group[returns].rank()))

    return obs.groupby("month")[[signal, returns]].apply(ic)


def monthly_spread(obs: pd.DataFrame, signal: str, returns: str) -> pd.Series:
    """Top-fifth minus bottom-fifth mean forward return, per month."""

    def spread(group: pd.DataFrame) -> float:
        group = group.dropna()
        if len(group) < MIN_CROSS_SECTION:
            return math.nan
        buckets = pd.qcut(group[signal].rank(method="first"), QUANTILES, labels=False)
        top = group.loc[buckets == QUANTILES - 1, returns].mean()
        bottom = group.loc[buckets == 0, returns].mean()
        return float(top - bottom)

    return obs.groupby("month")[[signal, returns]].apply(spread)


def signal_stats(
    obs: pd.DataFrame, horizons: Sequence[int], kind: str = "excess"
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """IC, quintile spread and hit rate per signal and horizon."""
    stats: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for signal in SIGNALS:
        if signal not in obs:
            continue
        stats[signal] = {}
        for h in horizons:
            column = f"{kind}_{h}m"
            spread = monthly_spread(obs, signal, column)
            hits = (spread.dropna() > 0).astype(float)
            stats[signal][f"{h}m"] = {
                "ic": mean_ci(monthly_ic(obs, signal, column), h - 1),
                "spread": mean_ci(spread, h - 1),
                "hit_rate": mean_ci(hits, h - 1),
            }
    return stats


def band_table(
    obs: pd.DataFrame,
    horizons: Sequence[int],
    thresholds: Optional[SignalThresholds] = None,
    kind: str = "excess",
) -> List[Dict[str, Any]]:
    """Forward returns by the composite's signal band, plus every observation as a baseline."""
    t = thresholds or SignalThresholds()
    ranges = {
        "Strong Buy": f">= {t.strong_buy:g}",
        "Buy": f"{t.buy:g}-{t.strong_buy:g}",
        "Hold": f"{t.hold_upper:g}-{t.buy:g}",
        "Sell": f"{t.sell:g}-{t.hold_upper:g}",
        "Strong Sell": f"< {t.sell:g}",
        "All": "",
    }
    scored = obs[obs["signal"].notna()] if "signal" in obs else obs.iloc[0:0]
    rows: List[Dict[str, Any]] = []
    for band in (*BANDS, "All"):
        members = scored if band == "All" else scored[scored["signal"] == band]
        row: Dict[str, Any] = {
            "band": band,
            "range": ranges[band],
            "observations": len(members),
            "share": len(members) / len(scored) if len(scored) else None,
        }
        for h in horizons:
            column = f"{kind}_{h}m"
            returns = members[column].dropna() if column in members else pd.Series(dtype=float)
            row[f"{h}m"] = {
                "mean": mean_ci(members.groupby("month")[column].mean(), h - 1)
                if len(returns)
                else None,
                "beat": float((returns > 0).mean()) if len(returns) else None,
            }
        rows.append(row)
    return rows


RETURN_KINDS = ("excess", "alpha", "ret")  # vs benchmark, beta-adjusted, raw


def summarize(
    obs: pd.DataFrame,
    horizons: Sequence[int],
    thresholds: Optional[SignalThresholds] = None,
) -> Dict[str, Any]:
    """Every table, for each kind of return the observations have."""
    return {
        kind: {
            "signals": signal_stats(obs, horizons, kind),
            "bands": band_table(obs, horizons, thresholds, kind),
        }
        for kind in RETURN_KINDS
        if f"{kind}_{horizons[0]}m" in obs
    }
