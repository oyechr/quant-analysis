"""
Vet a Ticker

One-screen verdict: score, red flags, peer valuation, signals, fund activity,
fair value range, and what would change the signal. Runs the analysis
pipeline with no file I/O (saving is up to the caller).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from ..data_fetcher import DataFetcher
from ..markets import ticker_suffix
from ..pipeline import AnalysisBundle, AnalysisOptions, analyze_ticker
from ..scoring import ScoringConfig, StockScorer
from ..utils.fx import normalize_info
from .ownership import FundActivity, fund_activity
from .peers import PeerValuation, peer_valuation
from .red_flags import RedFlag, find_red_flags
from .verdict import fair_value_range, signal_flip_prices

logger = logging.getLogger(__name__)

EARNINGS_SOON_DAYS = 14


@dataclass
class VetResult:
    ticker: str
    bundle: AnalysisBundle
    preset: str
    red_flags: List[RedFlag] = field(default_factory=list)
    peers: Optional[PeerValuation] = None
    funds: Optional[FundActivity] = None
    fair_value: Dict[str, Any] = field(default_factory=dict)
    signal_flips: Dict[str, Any] = field(default_factory=dict)
    next_earnings: Optional[str] = None
    next_steps: List[str] = field(default_factory=list)

    @property
    def report(self) -> Dict[str, Any]:
        return self.bundle.report

    def to_dict(self) -> Dict[str, Any]:
        info = self.report.get("info") or {}
        scoring = self.report.get("scoring") or {}
        data = {
            "ticker": self.ticker,
            "generated_at": self.report.get("generated_at"),
            "preset": self.preset,
            "header": {
                "name": info.get("name"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "currency": info.get("currency"),
                "price": self.fair_value.get("current_price"),
                "score": scoring.get("composite_score"),
                "signal": scoring.get("signal"),
                "confidence": scoring.get("confidence"),
                "dimensions": {
                    name: dim.get("score")
                    for name, dim in (scoring.get("dimensions") or {}).items()
                },
            },
            "red_flags": [f.to_dict() for f in self.red_flags],
            "peer_valuation": self.peers.to_dict() if self.peers else None,
            "signals": self.report.get("signals") or {},
            "fund_activity": self.funds.to_dict() if self.funds else None,
            "fair_value": self.fair_value,
            "signal_flips": self.signal_flips,
            "trade_levels": scoring.get("trade_levels"),
            "strengths": scoring.get("strengths") or [],
            "concerns": scoring.get("concerns") or [],
            "next_earnings": self.next_earnings,
            "next_steps": self.next_steps,
            "data_freshness": self.report.get("data_freshness"),
            "errors": self.bundle.errors,
        }
        data["verdict"] = summarize_verdict(data)
        return data


def vet_ticker(
    ticker: str,
    fetcher: Optional[DataFetcher] = None,
    options: Optional[AnalysisOptions] = None,
    peers: Optional[List[str]] = None,
    data_dir: str = "data",
) -> VetResult:
    """Analyze a ticker and assemble everything `quant vet` shows."""
    fetcher = fetcher or DataFetcher(cache_dir=data_dir)
    options = options or AnalysisOptions(include_context=False)
    config = options.scoring_config or ScoringConfig()
    ticker = ticker.upper()

    bundle = analyze_ticker(ticker, fetcher, options)
    report = bundle.report
    info = report.get("info") or {}
    result = VetResult(ticker=ticker, bundle=bundle, preset=config.name)

    # Peer valuation, then rescore so P/E is judged against the peers
    def fx_lookup(symbol: str) -> Optional[float]:
        return fetcher.latest_close(symbol, use_cache=options.use_cache)

    try:
        result.peers = peer_valuation(
            ticker,
            info,
            fetch_info=lambda t: normalize_info(
                fetcher.get_ticker_info(t, use_cache=options.use_cache), fx_lookup
            ),
            peers=peers,
            industry_peers=lambda key: fetcher.get_industry_peers(key, use_cache=options.use_cache),
            sector_peers=lambda key: fetcher.get_sector_peers(key, use_cache=options.use_cache),
            fx_lookup=fx_lookup,
            min_peers=config.valuation.min_peers,
        )
        report["peer_valuation"] = result.peers.to_dict()
        if bundle.scoring is not None:
            bundle.scoring = StockScorer(config=config).score(report)
            report["scoring"] = bundle.scoring.to_dict()
    except Exception as e:
        logger.warning(f"Peer valuation failed for {ticker}: {e}")
        bundle.errors["peer_valuation"] = str(e)

    result.red_flags = find_red_flags(report)
    result.funds = fund_activity(ticker, info.get("name"), data_dir=data_dir)
    result.fair_value = fair_value_range(report)
    try:
        result.signal_flips = signal_flip_prices(report, config)
    except Exception as e:
        logger.warning(f"Signal flip search failed for {ticker}: {e}")
    result.next_earnings = next_earnings_date(report)
    result.next_steps = next_steps(result, peers_given=bool(peers))
    return result


LOOK_DEEPER = "Look deeper"
WATCH = "Watch"
PASS = "Pass"

# A flip further away than this isn't actionable, so the summary leaves it out
MAX_FLIP_PCT = 50.0

_BUY_SIGNALS = ("Buy", "Strong Buy")
_SELL_SIGNALS = ("Sell", "Strong Sell")


def summarize_verdict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    The bottom line of a vet, from `VetResult.to_dict()` output.

    - Pass: a high-severity red flag, or a Sell/Strong Sell signal.
    - Look deeper: a Buy/Strong Buy signal with at least Medium confidence.
    - Watch: everything else.

    Reasons are short phrases, most decisive first.
    """
    header = data.get("header") or {}
    signal = header.get("signal")
    score = header.get("score")
    flags = data.get("red_flags") or []
    high = [f for f in flags if f.get("severity") == "high"]

    if high or signal in _SELL_SIGNALS:
        call = PASS
    elif signal in _BUY_SIGNALS and header.get("confidence") in ("High", "Medium"):
        call = LOOK_DEEPER
    else:
        call = WATCH

    reasons: List[str] = []
    if score is not None:
        reasons.append(f"{signal} {score:.0f}/100 ({header.get('confidence')} confidence)")
    if high:
        reasons.append(f"red flag: {high[0]['title'].lower()}")
    elif flags:
        reasons.append(f"{len(flags)} minor red flag(s)")
    else:
        reasons.append("no red flags")

    peer_view = _peer_view(data.get("peer_valuation") or {})
    if peer_view:
        reasons.append(peer_view)
    momentum = _momentum_view((data.get("signals") or {}).get("relative_strength") or {})
    if momentum:
        reasons.append(momentum)
    analysts = _analyst_view(data.get("fair_value") or {})
    if analysts:
        reasons.append(analysts)
    funds = _fund_view(data.get("fund_activity") or {})
    if funds:
        reasons.append(funds)
    if data.get("next_earnings"):
        days = (pd.Timestamp(data["next_earnings"]) - pd.Timestamp.now().normalize()).days
        if 0 <= days <= EARNINGS_SOON_DAYS:
            reasons.append(f"earnings in {days}d")

    flip = None
    flips = data.get("signal_flips") or {}
    for direction in ("up", "down"):
        target = flips.get(direction) or {}
        if target.get("price") is not None and abs(target.get("change_pct") or 0) <= MAX_FLIP_PCT:
            flip = {"direction": direction, **target}
            break

    return {"call": call, "reasons": reasons, "flip": flip}


def _peer_view(peers: Dict[str, Any]) -> Optional[str]:
    """Cheap/rich/in line, from the average cheapness across peer metrics."""
    ranks = [
        m["cheapness"]
        for m in (peers.get("metrics") or {}).values()
        if m.get("cheapness") is not None
    ]
    if not peers.get("peers") or not ranks:
        return None
    average = sum(ranks) / len(ranks)
    if average >= 65:
        view = "cheap"
    elif average <= 35:
        view = "expensive"
    else:
        view = "in line"
    return f"{view} vs {len(peers['peers'])} peers"


def _momentum_view(rs: Dict[str, Any]) -> Optional[str]:
    rating = rs.get("rs_rating")
    if rating is None:
        return None
    if rating >= 70:
        return f"strong momentum (RS {rating})"
    if rating <= 30:
        return f"weak momentum (RS {rating})"
    return None


def _analyst_view(fair_value: Dict[str, Any]) -> Optional[str]:
    """Analyst mean target vs price, when at least 3 analysts cover the stock."""
    analysts = fair_value.get("analysts") or {}
    upside = (fair_value.get("upside_pct") or {}).get("analyst_mean")
    if upside is None or (analysts.get("count") or 0) < 3:
        return None
    return f"analyst target {upside:+.0f}%"


def _fund_view(funds: Dict[str, Any]) -> Optional[str]:
    positions = funds.get("positions") or []
    buying = sum(1 for p in positions if p.get("action") in ("new", "add"))
    selling = sum(1 for p in positions if p.get("action") in ("trim", "exit"))
    if not buying and not selling:
        return None
    return f"tracked funds: {buying} buying, {selling} selling"


def next_earnings_date(report: Dict[str, Any], today: Optional[datetime] = None) -> Optional[str]:
    """Earliest upcoming earnings date in the report, as YYYY-MM-DD."""
    today = today or datetime.now()
    upcoming = []
    for row in (report.get("earnings") or {}).get("upcoming_dates") or []:
        stamp = row.get("Earnings Date") or row.get("index")
        if stamp is None:
            continue
        try:
            date = pd.Timestamp(stamp)
        except ValueError, TypeError:
            continue
        date = date.tz_localize(None) if date.tzinfo is not None else date
        if date.normalize() >= pd.Timestamp(today).normalize():
            upcoming.append(date)
    return str(min(upcoming).date()) if upcoming else None


def next_steps(result: VetResult, peers_given: bool) -> List[str]:
    """Concrete follow-ups based on what the vet found (and didn't)."""
    t = result.ticker
    steps: List[str] = []

    high = [f for f in result.red_flags if f.severity == "high"]
    if high:
        steps.append(f"Resolve the {len(high)} high-severity red flag(s) before going further")

    if result.next_earnings:
        days = (pd.Timestamp(result.next_earnings) - pd.Timestamp.now().normalize()).days
        if 0 <= days <= EARNINGS_SOON_DAYS:
            steps.append(
                f"Earnings on {result.next_earnings} ({days}d): consider waiting for results"
            )

    peers = result.peers
    if peers is None or not peers.peers:
        steps.append(
            "No similar-size peers in Yahoo's industry or sector lists: pass --peers T1,T2,..."
        )
    elif not peers_given and len(peers.peers) < 4:
        steps.append(
            f"Only {len(peers.peers)} similar-size peer(s) found; "
            "add --peers for a firmer comparison"
        )
    elif not peers_given and (suffix := ticker_suffix(t)):
        steps.append(
            f"Yahoo's peer lists are mostly US companies; for home-market peers "
            f"pass --peers T1{suffix},T2{suffix},..."
        )

    if result.funds is not None and result.funds.hint:
        steps.append(result.funds.hint.replace("No 13F cache found. ", ""))

    steps.append(f"Full write-up: quant report {t}")
    if peers and peers.peers:
        steps.append(f"Side by side: quant compare {t} {' '.join(peers.peers[:3])}")
    steps.append(f"Ask questions: quant chat {t}")
    return steps
