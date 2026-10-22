"""
What Changed

`quant changes`: rescore the watchlist (or given tickers), record the run in
the score history, and compare each ticker with its latest row from an
earlier day: score and signal, red flags that appeared or cleared, the price
move, price against the watchlist target/stop, and earnings coming up.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions, analyze_ticker
from ..scoring import ScoringConfig
from ..utils.concurrency import DEFAULT_WORKERS, run_concurrently
from ..vetting.red_flags import find_red_flags
from ..vetting.render import Section, Table, sections_to_text
from ..vetting.vet import EARNINGS_SOON_DAYS, next_earnings_date
from .history import DIMENSIONS, Row, flag_titles, history_row, load_history, record_scores
from .watchlist import WatchItem

SCORE_MOVE = 3.0  # composite points worth mentioning
DIMENSION_MOVE = 5.0  # dimension points worth mentioning
NEAR_LEVEL_PCT = 5.0  # mention a target/stop this close to the price


@dataclass
class TickerChange:
    ticker: str
    today: date
    name: Optional[str] = None
    current: Optional[Row] = None
    previous: Optional[Row] = None
    watch: Optional[WatchItem] = None
    next_earnings: Optional[str] = None
    error: Optional[str] = None

    @property
    def score_delta(self) -> Optional[float]:
        return _delta(self.current, self.previous, "score")

    @property
    def price_change_pct(self) -> Optional[float]:
        cur, prev = self.current or {}, self.previous or {}
        if not cur.get("price") or not prev.get("price"):
            return None
        if cur.get("currency") != prev.get("currency"):
            return None
        return (cur["price"] / prev["price"] - 1) * 100

    @property
    def signal_change(self) -> Optional[tuple[str, str]]:
        if not self.current or not self.previous:
            return None
        old, new = self.previous.get("signal"), self.current.get("signal")
        return (old, new) if old and new and old != new else None

    @property
    def new_flags(self) -> List[str]:
        if self.previous is None:
            return []
        before = set(flag_titles(self.previous))
        return [t for t in flag_titles(self.current) if t not in before]

    @property
    def resolved_flags(self) -> List[str]:
        if self.previous is None:
            return []
        now = set(flag_titles(self.current))
        return [t for t in flag_titles(self.previous) if t not in now]

    @property
    def earnings_in_days(self) -> Optional[int]:
        if not self.next_earnings:
            return None
        days = (pd.Timestamp(self.next_earnings) - pd.Timestamp(self.today)).days
        return days if 0 <= days <= EARNINGS_SOON_DAYS else None

    def notes(self) -> List[str]:
        """What is worth a look, most decisive first."""
        notes: List[str] = []
        if self.signal_change:
            notes.append(f"signal {self.signal_change[0]} -> {self.signal_change[1]}")
        delta = self.score_delta
        if delta is not None and abs(delta) >= SCORE_MOVE:
            old, new = (self.previous or {}).get("score"), (self.current or {}).get("score")
            notes.append(f"score {old:.0f} -> {new:.0f} ({delta:+.0f})")
        moves = [
            f"{name} {d:+.0f}"
            for name in DIMENSIONS
            if (d := _delta(self.current, self.previous, name)) is not None
            and abs(d) >= DIMENSION_MOVE
        ]
        if moves:
            notes.append(f"dimensions: {', '.join(moves)}")
        notes += [f"new red flag: {t}" for t in self.new_flags]
        notes += [f"red flag cleared: {t}" for t in self.resolved_flags]
        notes += self._level_notes()
        if self.earnings_in_days is not None:
            notes.append(f"earnings {self.next_earnings} ({self.earnings_in_days}d)")
        return notes

    def _level_notes(self) -> List[str]:
        price = (self.current or {}).get("price")
        if not price or self.watch is None:
            return []
        notes: List[str] = []
        target, stop = self.watch.target, self.watch.stop
        if target is not None:
            if price >= target:
                notes.append(f"reached target {target:g} (price {price:,.2f})")
            elif (gap := (target - price) / price * 100) <= NEAR_LEVEL_PCT:
                notes.append(f"{gap:.1f}% below target {target:g}")
        if stop is not None:
            if price <= stop:
                notes.append(f"below stop {stop:g} (price {price:,.2f})")
            elif (gap := (price - stop) / price * 100) <= NEAR_LEVEL_PCT:
                notes.append(f"{gap:.1f}% above stop {stop:g}")
        return notes

    def sort_key(self) -> tuple[int, int, float]:
        """Errors last; then signal changes, then the biggest score moves."""
        if self.error:
            return (2, 0, 0.0)
        return (
            0 if self.notes() else 1,
            0 if self.signal_change else 1,
            -abs(self.score_delta or 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "current": self.current,
            "previous": self.previous,
            "score_delta": self.score_delta,
            "price_change_pct": self.price_change_pct,
            "signal_change": list(self.signal_change) if self.signal_change else None,
            "new_flags": self.new_flags,
            "resolved_flags": self.resolved_flags,
            "target": self.watch.target if self.watch else None,
            "stop": self.watch.stop if self.watch else None,
            "thesis": self.watch.thesis if self.watch else None,
            "next_earnings": self.next_earnings,
            "notes": self.notes(),
            "error": self.error,
        }


@dataclass
class ChangesResult:
    preset: str
    today: date
    changes: List[TickerChange] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preset": self.preset,
            "date": self.today.isoformat(),
            "changes": [c.to_dict() for c in self.changes],
        }


def track_changes(
    tickers: Sequence[str],
    fetcher: Optional[DataFetcher] = None,
    options: Optional[AnalysisOptions] = None,
    watchlist: Optional[Dict[str, WatchItem]] = None,
    data_dir: str = "data",
    workers: int = DEFAULT_WORKERS,
    today: Optional[date] = None,
    progress: Optional[Callable[[str, Optional[Exception]], None]] = None,
) -> ChangesResult:
    """Rescore each ticker, record it, and compare with its last earlier run."""
    fetcher = fetcher or DataFetcher(cache_dir=data_dir)
    options = options or AnalysisOptions(include_context=False)
    preset = (options.scoring_config or ScoringConfig()).name
    today = today or date.today()
    watchlist = watchlist or {}
    tickers = list(dict.fromkeys(t.upper() for t in tickers))

    # Latest row per ticker from an earlier day, read before today's rows go in
    previous: Dict[str, Row] = {}
    for row in load_history(data_dir, preset=preset):
        if row["date"] < today.isoformat():
            previous[row["ticker"]] = row

    def analyze(ticker: str) -> Any:
        bundle = analyze_ticker(ticker, fetcher, options)
        return bundle, find_red_flags(bundle.report)

    result = ChangesResult(preset=preset, today=today)
    rows: List[Row] = []
    for ticker, outcome, error in run_concurrently(analyze, tickers, workers=workers):
        change = TickerChange(
            ticker=ticker, today=today, previous=previous.get(ticker), watch=watchlist.get(ticker)
        )
        if error is not None or outcome is None:
            change.error = str(error or "no result")
        else:
            bundle, flags = outcome
            info = bundle.report.get("info") or {}
            change.name = info.get("name")
            row = history_row(bundle.report, bundle.scoring, "changes", flags, today)
            if row is None:
                change.error = bundle.errors.get("scoring") or "no price data (check the symbol)"
            else:
                change.current = row
                rows.append(row)
            change.next_earnings = next_earnings_date(
                bundle.report, today=datetime.combine(today, time())
            )
        if progress:
            progress(ticker, error)
        result.changes.append(change)

    record_scores(rows, data_dir)
    result.changes.sort(key=TickerChange.sort_key)
    return result


# ==================== Output ====================


def render_text(data: Dict[str, Any]) -> str:
    """Terminal layout from `ChangesResult.to_dict()`."""
    changes = data.get("changes") or []
    scored = [c for c in changes if not c.get("error")]
    rows = []
    for c in scored:
        cur, prev = c["current"], c.get("previous")
        signal = cur.get("signal") or ""
        if c.get("signal_change"):
            signal = " -> ".join(c["signal_change"])
        rows.append(
            [
                c["ticker"],
                _fmt(cur.get("score"), "{:.0f}"),
                _fmt(c.get("score_delta"), "{:+.0f}") if prev else "new",
                signal,
                _fmt(cur.get("price"), "{:,.2f}"),
                _fmt(c.get("price_change_pct"), "{:+.1f}%"),
                prev["date"] if prev else "",
            ]
        )
    summary: List[Any] = (
        [Table(["Ticker", "Score", "Chg", "Signal", "Price", "Chg %", "Since"], rows, "lrrlrrl")]
        if rows
        else ["Nothing scored."]
    )
    sections = [Section(f"CHANGES  {data.get('date')}  (preset: {data.get('preset')})", summary)]

    moved = [c for c in scored if c.get("notes")]
    if moved:
        blocks: List[Any] = []
        for c in moved:
            title = f"{c['ticker']}  {c['name']}" if c.get("name") else c["ticker"]
            if blocks:
                blocks.append("")
            blocks.append(title)
            blocks += [f"  - {note}" for note in c["notes"]]
        sections.append(Section("WORTH A LOOK", blocks))

    quiet = [c["ticker"] for c in scored if c.get("previous") and not c.get("notes")]
    first = [c["ticker"] for c in scored if not c.get("previous")]
    failed = [f"{c['ticker']}: {c['error']}" for c in changes if c.get("error")]
    notes: List[Any] = []
    if quiet:
        notes.append(f"No notable change: {', '.join(quiet)}")
    if first:
        notes.append(f"First run, baseline recorded: {', '.join(first)}")
    notes += [f"Not scored: {line}" for line in failed]
    notes.append(
        f"Compared with each ticker's latest run before today; moves under "
        f"{SCORE_MOVE:g} points aren't listed."
    )
    if moved:
        notes.append(f"Dig in: quant vet {moved[0]['ticker']}")
    sections.append(Section("NOTES", notes))
    return sections_to_text(sections)


def _delta(current: Optional[Row], previous: Optional[Row], column: str) -> Optional[float]:
    if not current or not previous:
        return None
    new, old = current.get(column), previous.get(column)
    if new is None or old is None:
        return None
    return float(new) - float(old)


def _fmt(value: Optional[float], pattern: str) -> str:
    return "" if value is None else pattern.format(value)
