"""
Peer-Relative Valuation

Compares a ticker's multiples (P/E, forward P/E, EV/EBITDA, P/S, P/B, FCF
yield) with a peer group's median and reports where it ranks.

Peer rule: the `--peers` you give; otherwise Yahoo's industry list, topped
up from its sector list when fewer than `min_peers` remain, keeping only
companies within 10x of the target's USD market cap and dropping other
listings of the same company.

Ratios are Yahoo's own (TTM). For tickers whose statements are in another
currency than their price, the caller normalizes them first
(`utils.fx.normalize_info`); ratios that couldn't be converted are skipped
(see `metric_value`).
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from ..utils.concurrency import run_concurrently
from ..utils.financial import finite_float
from ..utils.fx import major_currency, usd_per_unit

logger = logging.getLogger(__name__)

InfoLookup = Callable[[str], dict[str, Any]]
ListLookup = Callable[[str], list[str]]
FxLookup = Callable[[str], float | None]

MAX_YAHOO_PEERS = 10
MAX_YAHOO_CANDIDATES = 25  # info is fetched for each before the size filter
SIZE_BAND = 10.0  # Yahoo peers must be within 10x of the target's market cap
PEER_FETCH_WORKERS = 4


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    lower_is_cheaper: bool = True


METRICS: list[Metric] = [
    Metric("pe_ratio", "P/E"),
    Metric("forward_pe", "Fwd P/E"),
    Metric("ev_to_ebitda", "EV/EBITDA"),
    Metric("price_to_sales", "P/S"),
    Metric("price_to_book", "P/B"),
    Metric("fcf_yield", "FCF yield %", lower_is_cheaper=False),
]


@dataclass
class MetricComparison:
    key: str
    label: str
    value: float | None
    median: float | None
    percentile: float | None  # 0-100: share of peers below the target's value
    cheapness: float | None  # 0-100: share of peers more expensive than the target
    n: int  # peers with a usable value

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": _round(self.value),
            "median": _round(self.median),
            "percentile": _round(self.percentile, 0),
            "cheapness": _round(self.cheapness, 0),
            "n": self.n,
        }


@dataclass
class PeerValuation:
    ticker: str
    peers: list[str]
    basis: str  # "explicit", "yahoo_industry", "yahoo_industry_sector", "yahoo_sector", "none"
    group: str | None = None  # the industry/sector name used
    metrics: dict[str, MetricComparison] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)  # requested peers with no data

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "basis": self.basis,
            "group": self.group,
            "peers": self.peers,
            "missing": self.missing,
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
        }


# ==================== Maths ====================


def percentile_rank(value: float, population: list[float]) -> float | None:
    """
    Percent of `population` below `value`, counting ties as half (0-100).

    With peers [10, 20, 30, 40], a value of 25 ranks 50; a value of 20 ranks 37.5.
    """
    if not population:
        return None
    below = sum(1 for p in population if p < value)
    equal = sum(1 for p in population if p == value)
    return (below + 0.5 * equal) / len(population) * 100


def metric_value(info: dict[str, Any], key: str) -> float | None:
    """
    A comparable metric value from an info dict, or None if unusable.

    Multiples must be positive (a negative P/E has no meaningful rank).
    Statement-based ratios (P/S, EV/EBITDA, P/B, FCF yield) are skipped when
    the statements are in another currency than the price and the ratio isn't
    in `converted_ratios` (see utils.fx.adjust_info_ratios).
    """
    if key in _STATEMENT_RATIOS and _mixed_currency(info, key):
        return None
    if key == "fcf_yield":
        fcf = finite_float(info.get("free_cashflow"))
        mcap = finite_float(info.get("market_cap"))
        if fcf is None or not mcap or mcap <= 0:
            return None
        return fcf / mcap * 100
    value = finite_float(info.get(key))
    return value if value is not None and value > 0 else None


# Ratios Yahoo can compute from statement-currency values (see utils.fx.adjust_info_ratios)
_STATEMENT_RATIOS = ("price_to_sales", "ev_to_ebitda", "price_to_book", "fcf_yield")


def _mixed_currency(info: dict[str, Any], key: str) -> bool:
    """
    Whether a statement-based ratio may mix currencies.

    True when statements are in another currency than the price and the ratio
    wasn't converted (FCF yield never is), and for non-USD listings whose
    statement currency is unknown.
    """
    statements, listing = info.get("financial_currency"), info.get("currency")
    if not listing:
        return False
    if not statements:
        return bool(major_currency(str(listing))[0] != "USD")
    # GBP statements on a GBp listing: Yahoo's ratios use the GBP market cap
    if major_currency(str(statements))[0] == major_currency(str(listing))[0]:
        return False
    return key not in (info.get("converted_ratios") or [])


def compare_to_peers(
    ticker: str,
    target_info: dict[str, Any],
    peer_infos: dict[str, dict[str, Any]],
    basis: str,
    group: str | None = None,
) -> PeerValuation:
    """Median and percentile of the target on each metric against the peers."""
    result = PeerValuation(ticker=ticker, peers=list(peer_infos), basis=basis, group=group)
    for metric in METRICS:
        values = [
            v
            for v in (metric_value(info, metric.key) for info in peer_infos.values())
            if v is not None
        ]
        target = metric_value(target_info, metric.key)
        pct = percentile_rank(target, values) if target is not None else None
        cheapness = None
        if pct is not None:
            cheapness = 100 - pct if metric.lower_is_cheaper else pct
        result.metrics[metric.key] = MetricComparison(
            key=metric.key,
            label=metric.label,
            value=target,
            median=median(values) if values else None,
            percentile=pct,
            cheapness=cheapness,
            n=len(values),
        )
    return result


# ==================== Peer selection ====================


def peer_valuation(
    ticker: str,
    info: dict[str, Any],
    fetch_info: InfoLookup,
    peers: list[str] | None = None,
    industry_peers: ListLookup | None = None,
    sector_peers: ListLookup | None = None,
    fx_lookup: FxLookup | None = None,
    min_peers: int = 4,
) -> PeerValuation:
    """
    Compare `ticker` with explicit `peers`, or with Yahoo's industry/sector peers.

    Args:
        ticker: The target's symbol
        info: The target's info dict (from the pipeline report)
        fetch_info: Symbol -> info dict, normalized (utils.fx.normalize_info)
        peers: Explicit peer symbols; used as given, with no size filter
        industry_peers / sector_peers: Yahoo key -> symbols (DataFetcher.get_*_peers)
        fx_lookup: Yahoo FX symbol -> latest close, to compare market caps in USD
        min_peers: Below this many industry peers, top up from the sector list
    """
    ticker = ticker.upper()

    if peers:
        loaded, missing = _load_infos(ticker, peers, fetch_info)
        result = compare_to_peers(ticker, info, _drop_same_company(info, loaded), "explicit")
        result.missing = missing
        return result

    chosen = _yahoo_group(ticker, info, "industry", industry_peers, fetch_info, fx_lookup)
    kind = "industry"
    if len(chosen) < min_peers:
        # Industry peers stay first; the sector list only fills the gap
        sector = _yahoo_group(ticker, info, "sector", sector_peers, fetch_info, fx_lookup)
        if sector.keys() - chosen.keys():
            kind = "industry_sector" if chosen else "sector"
            chosen = {**chosen, **sector}
    if not chosen:
        return compare_to_peers(ticker, info, {}, "none")
    chosen = dict(list(chosen.items())[:MAX_YAHOO_PEERS])
    group = info.get("industry" if kind == "industry" else "sector")
    return compare_to_peers(ticker, info, chosen, f"yahoo_{kind}", group=group)


def _yahoo_group(
    ticker: str,
    info: dict[str, Any],
    kind: str,
    lister: ListLookup | None,
    fetch_info: InfoLookup,
    fx_lookup: FxLookup | None,
) -> dict[str, dict[str, Any]]:
    """Similar-size peers from Yahoo's list for the target's industry or sector, closest first."""
    key = info.get(f"{kind}_key")
    if lister is None or not key:
        return {}
    try:
        symbols = lister(key)
    except Exception as e:  # Yahoo lookups are best effort
        logger.warning(f"Yahoo {kind} peers unavailable for {ticker}: {e}")
        return {}
    loaded, _ = _load_infos(ticker, symbols[:MAX_YAHOO_CANDIDATES], fetch_info)
    return _similar_size(info, _drop_same_company(info, loaded), fx_lookup)


def _similar_size(
    info: dict[str, Any],
    peers: dict[str, dict[str, Any]],
    fx_lookup: FxLookup | None,
) -> dict[str, dict[str, Any]]:
    """Peers within SIZE_BAND of the target's USD market cap, closest first."""
    target = _usd_market_cap(info, fx_lookup)
    if target is None:
        return peers
    sized = {t: _usd_market_cap(i, fx_lookup) for t, i in peers.items()}
    within = {
        t: cap for t, cap in sized.items() if cap and 1 / SIZE_BAND <= cap / target <= SIZE_BAND
    }
    ranked = sorted(within, key=lambda t: abs(math.log(within[t] / target)))
    return {t: peers[t] for t in ranked}


def _usd_market_cap(info: dict[str, Any], fx_lookup: FxLookup | None) -> float | None:
    cap = finite_float(info.get("market_cap"))
    if cap is None or cap <= 0:
        return None
    # Yahoo's market cap is in the major currency even for a minor-unit
    # listing (BARC.L: GBP, priced in pence), so convert from the major one
    currency = major_currency(str(info.get("currency") or "USD"))[0]
    if currency == "USD":
        return cap
    rate = usd_per_unit(currency, fx_lookup) if fx_lookup else None
    return cap * rate if rate else None


def _load_infos(
    ticker: str, symbols: list[str], fetch_info: InfoLookup
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Info dicts for `symbols` in the given order, plus the symbols with no data."""
    wanted = [t for t in dict.fromkeys(s.upper() for s in symbols) if t != ticker]
    results: dict[str, dict[str, Any]] = {}
    for symbol, peer_info, error in run_concurrently(
        fetch_info, wanted, workers=PEER_FETCH_WORKERS
    ):
        if error is not None:  # one bad peer shouldn't sink the comparison
            logger.warning(f"Could not load info for peer {symbol}: {error}")
        elif peer_info:
            results[symbol] = peer_info
    loaded = {t: results[t] for t in wanted if t in results}
    return loaded, [t for t in wanted if t not in results]


def _drop_same_company(
    info: dict[str, Any], peers: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Leave out other share classes / listings of the target (GOOG for GOOGL, EQNR for EQNR.OL)."""
    name = _clean(info.get("name"))
    if not name:
        return peers
    return {t: i for t, i in peers.items() if _clean(i.get("name")) != name}


def _clean(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "" if text in ("", "n/a", "none", "unknown") else text


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)
