"""
Decision Journal

One entry per buy, add, trim or sell, kept in `portfolio/journal.toml`
(gitignored: it's personal). A buy or add records the thesis and what would
prove it wrong; `check_thesis` tests each open one against the latest score
history row, and `look_back` measures every decision against its home
benchmark.

    [[decision]]
    date = 2026-11-04
    ticker = "EQNR.OL"
    action = "buy"
    thesis = "Cheap vs peers if oil holds above $70"
    exit_if = "Capex guidance up again"
    price = 432.0
    stop = 380.0
    target = 500.0
    min_score = 50.0
    review_by = 2027-05-01
    preset = "default"
    score = 62.0
    signal = "Hold"
    currency = "NOK"
    flags = ["Weak interest coverage"]

Prices are in the listing currency. preset, score, signal, currency and
flags (every red flag's title) are a snapshot of the score history at the
decision. A sell sets `closed` on the ticker's open buys and adds. The file
is meant to be editable by hand; `quant journal add` rewrites it in the same
layout, without comments or keys it doesn't know.
"""

import datetime as dt
import math
import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ..utils.files import atomic_write_text
from ..utils.financial import trading_dates
from ..vetting.render import Section, Table, sections_to_text
from .history import Row, flag_titles
from .watchlist import _toml_string

DEFAULT_JOURNAL = "portfolio/journal.toml"
ACTIONS = ("buy", "add", "trim", "sell")
OPENING = ("buy", "add")  # actions that carry a thesis to check

SELL_SIGNALS = ("Sell", "Strong Sell")
THESIS_SCORE_DROP = 10.0  # composite points lost since the decision worth a recheck
STALE_DAYS = 7  # a latest score older than this is flagged
SNAPSHOT_MAX_DAYS = 7  # a backdated decision takes a history row at most this old

BROKEN = "Broken"
CHECK = "Check"
OK = "OK"

_OPTIONAL_FIELDS = ("thesis", "exit_if", "price", "shares", "stop", "target", "min_score")
_SNAPSHOT_FIELDS = ("preset", "score", "signal", "currency")


@dataclass
class Decision:
    ticker: str
    date: dt.date
    action: str
    thesis: Optional[str] = None  # the reason, for a trim or sell
    exit_if: Optional[str] = None
    price: Optional[float] = None
    shares: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    min_score: Optional[float] = None
    review_by: Optional[dt.date] = None
    # Snapshot of the score history at the decision
    preset: Optional[str] = None
    score: Optional[float] = None
    signal: Optional[str] = None
    currency: Optional[str] = None
    # Every red flag's title: history rows before 2026-11 don't say which were high
    flags: List[str] = field(default_factory=list)
    closed: Optional[dt.date] = None

    @property
    def is_open(self) -> bool:
        return self.action in OPENING and self.closed is None

    def take_snapshot(self, row: Optional[Row]) -> None:
        """Copy the score, signal and red flags from a history row (and the price, if unset)."""
        if not row:
            return
        self.preset = row.get("preset")
        self.score = row.get("score")
        self.signal = row.get("signal")
        self.currency = row.get("currency")
        self.flags = flag_titles(row)
        if self.price is None:
            self.price = row.get("price")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "date": self.date.isoformat(),
            "action": self.action,
            **{name: getattr(self, name) for name in _OPTIONAL_FIELDS},
            "review_by": self.review_by.isoformat() if self.review_by else None,
            **{name: getattr(self, name) for name in _SNAPSHOT_FIELDS},
            "flags": self.flags,
            "closed": self.closed.isoformat() if self.closed else None,
        }


# ==================== File ====================


def load_journal(path: Path) -> List[Decision]:
    """Decisions in file order; empty if the file doesn't exist."""
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Can't read {path}: {e}") from e

    decisions: List[Decision] = []
    for i, entry in enumerate(data.get("decision") or [], 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: decision {i} should be a [[decision]] table")
        ticker = str(entry.get("ticker") or "").strip().upper()
        day = _date(entry.get("date"))
        action = str(entry.get("action") or "").lower()
        if not ticker or day is None or action not in ACTIONS:
            raise ValueError(
                f"{path}: decision {i} needs a ticker, a date (2026-11-04) and an action "
                f"({', '.join(ACTIONS)})"
            )
        decisions.append(
            Decision(
                ticker=ticker,
                date=day,
                action=action,
                thesis=_text(entry.get("thesis")),
                exit_if=_text(entry.get("exit_if")),
                price=_number(entry.get("price")),
                shares=_number(entry.get("shares")),
                stop=_number(entry.get("stop")),
                target=_number(entry.get("target")),
                min_score=_number(entry.get("min_score")),
                review_by=_date(entry.get("review_by")),
                preset=_text(entry.get("preset")),
                score=_number(entry.get("score")),
                signal=_text(entry.get("signal")),
                currency=_text(entry.get("currency")),
                # high_flags: the key in the first entries (2026-11-04)
                flags=[str(t) for t in entry.get("flags") or entry.get("high_flags") or []],
                closed=_date(entry.get("closed")),
            )
        )
    return decisions


def save_journal(decisions: Sequence[Decision], path: Path) -> None:
    lines: List[str] = []
    for d in decisions:
        lines += ["[[decision]]", f"date = {d.date.isoformat()}", f"ticker = {_toml(d.ticker)}"]
        lines.append(f"action = {_toml(d.action)}")
        for name in _OPTIONAL_FIELDS:
            if (value := getattr(d, name)) is not None:
                lines.append(f"{name} = {_toml(value)}")
        if d.review_by:
            lines.append(f"review_by = {d.review_by.isoformat()}")
        for name in _SNAPSHOT_FIELDS:
            if (value := getattr(d, name)) is not None:
                lines.append(f"{name} = {_toml(value)}")
        if d.score is not None or d.flags:
            lines.append(f"flags = {_toml(d.flags)}")
        if d.closed:
            lines.append(f"closed = {d.closed.isoformat()}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, "\n".join(lines))


def add_decision(path: Path, decision: Decision) -> List[Decision]:
    """
    Append a decision. A sell closes the ticker's open buys and adds as of its
    date; returns the decisions it closed.
    """
    if decision.action not in ACTIONS:
        raise ValueError(f"Unknown action '{decision.action}' (use {', '.join(ACTIONS)})")
    decisions = load_journal(path)
    closed: List[Decision] = []
    if decision.action == "sell":
        for d in decisions:
            if d.ticker == decision.ticker and d.is_open and d.date <= decision.date:
                d.closed = decision.date
                closed.append(d)
    decisions.append(decision)
    save_journal(decisions, path)
    return closed


def snapshot_row(rows: Sequence[Row], day: date) -> Optional[Row]:
    """The latest history row on or before `day`, at most SNAPSHOT_MAX_DAYS old."""
    earliest = (day - timedelta(days=SNAPSHOT_MAX_DAYS)).isoformat()
    candidates = [r for r in rows if earliest <= r["date"] <= day.isoformat()]
    return candidates[-1] if candidates else None


# ==================== Thesis check ====================


@dataclass
class ThesisCheck:
    decision: Decision
    current: Optional[Row]  # the latest history row for the ticker and preset
    broken: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    previous_status: Optional[str] = None  # on the ticker's latest row before today

    @property
    def status(self) -> str:
        return BROKEN if self.broken else CHECK if self.warnings else OK

    @property
    def is_new(self) -> bool:
        """Worse than on the previous run (no earlier row counts as OK)."""
        return _RANK[self.status] < _RANK[self.previous_status or OK]

    @property
    def return_pct(self) -> Optional[float]:
        return _return_pct(self.decision, self.current)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "current": self.current,
            "status": self.status,
            "previous_status": self.previous_status,
            "new": self.is_new,
            "broken": self.broken,
            "warnings": self.warnings,
            "return_pct": self.return_pct,
        }


_RANK = {BROKEN: 0, CHECK: 1, OK: 2}


def check_thesis(
    decision: Decision, current: Optional[Row], today: date
) -> Tuple[List[str], List[str]]:
    """
    (broken, warnings) for an open buy or add.

    Broken: below the stop, score under the minimum, or a Sell signal or high
    red flag that wasn't there at the decision. Worth a recheck: target
    reached, review date reached, the score down THESIS_SCORE_DROP points
    since the decision, or no recent score.
    """
    broken: List[str] = []
    warnings: List[str] = []
    if current is None:
        return broken, ["no score yet: run quant changes"]

    price, score, signal = current.get("price"), current.get("score"), current.get("signal")
    if price is not None and decision.stop is not None and price <= decision.stop:
        broken.append(f"below stop {decision.stop:g} (price {price:,.2f})")
    if score is not None and decision.min_score is not None and score < decision.min_score:
        broken.append(f"score {score:.0f} under the minimum {decision.min_score:g}")
    if signal in SELL_SIGNALS and decision.signal not in SELL_SIGNALS:
        broken.append(f"signal {decision.signal or '?'} -> {signal}")
    broken += [
        f"new high red flag: {t}"
        for t in flag_titles(current, "high_flags")
        if t not in decision.flags
    ]

    if price is not None and decision.target is not None and price >= decision.target:
        warnings.append(f"reached target {decision.target:g} (price {price:,.2f})")
    if decision.review_by is not None and decision.review_by <= today:
        warnings.append(f"review date {decision.review_by.isoformat()} reached")
    if score is not None and decision.score is not None:
        if decision.score - score >= THESIS_SCORE_DROP:
            warnings.append(
                f"score {decision.score:.0f} -> {score:.0f} since {decision.date.isoformat()}"
            )
    if current["date"] < (today - timedelta(days=STALE_DAYS)).isoformat():
        warnings.append(f"last scored {current['date']}")
    return broken, warnings


def check_journal(
    decisions: Sequence[Decision],
    history: Sequence[Row],
    today: Optional[date] = None,
    previous: Optional[Sequence[Row]] = None,
) -> List[ThesisCheck]:
    """
    Check every open buy and add against its ticker's latest history row;
    broken first. `previous_status` is the same check on the latest row in
    `previous` (the history before this run; default: the rows before
    today), as of that row's date.
    """
    today = today or date.today()
    latest = _latest_rows(history, today, include_today=True)
    if previous is None:
        before = _latest_rows(history, today, include_today=False)
    else:
        before = _latest_rows(previous, today, include_today=True)

    checks: List[ThesisCheck] = []
    for d in decisions:
        if not d.is_open:
            continue
        key = (d.ticker, d.preset or "default")
        current = latest.get(key)
        broken, warnings = check_thesis(d, current, today)
        check = ThesisCheck(d, current, broken, warnings)
        if (earlier := before.get(key)) is not None and earlier["date"] >= d.date.isoformat():
            as_of = date.fromisoformat(earlier["date"])
            was_broken, was_warned = check_thesis(d, earlier, as_of)
            check.previous_status = BROKEN if was_broken else CHECK if was_warned else OK
        checks.append(check)
    return sorted(checks, key=lambda c: (_RANK[c.status], c.decision.date))


def _latest_rows(
    rows: Sequence[Row], today: date, include_today: bool
) -> Dict[Tuple[str, str], Row]:
    """The latest row per (ticker, preset) up to today, or up to yesterday."""
    latest: Dict[Tuple[str, str], Row] = {}
    for row in rows:  # oldest first, so the last one wins
        if row["date"] < today.isoformat() or (include_today and row["date"] == today.isoformat()):
            latest[(row["ticker"], row["preset"])] = row
    return latest


# ==================== Look-back ====================


@dataclass
class Outcome:
    """How a decision did: the ticker against its home benchmark, decision close to `end`."""

    decision: Decision
    end: date
    benchmark: str
    ticker_return: Optional[float] = None  # percent
    benchmark_return: Optional[float] = None  # percent

    @property
    def excess(self) -> Optional[float]:
        if self.ticker_return is None or self.benchmark_return is None:
            return None
        return self.ticker_return - self.benchmark_return

    @property
    def good_call(self) -> Optional[bool]:
        """A buy or add that beat the benchmark, or a trim or sell that lagged it."""
        if self.excess is None:
            return None
        return self.excess > 0 if self.decision.action in OPENING else self.excess < 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "end": self.end.isoformat(),
            "benchmark": self.benchmark,
            "ticker_return": self.ticker_return,
            "benchmark_return": self.benchmark_return,
            "excess": self.excess,
            "good_call": self.good_call,
        }


def look_back(
    decisions: Sequence[Decision],
    closes: Callable[[str], Optional[pd.Series]],
    benchmark_for: Callable[[str], str],
    today: Optional[date] = None,
    since: Optional[date] = None,
) -> List[Outcome]:
    """
    Each decision from `since` on, from the close on its date to the close on
    the day it was closed (a buy or add later sold) or today. A trim or sell
    is measured to today: what the money would have done had it stayed.
    """
    today = today or date.today()
    outcomes: List[Outcome] = []
    for d in decisions:
        if since is not None and d.date < since:
            continue
        end = d.closed or today
        bench = benchmark_for(d.ticker)
        outcomes.append(
            Outcome(
                decision=d,
                end=end,
                benchmark=bench,
                ticker_return=period_return(closes(d.ticker), d.date, end),
                benchmark_return=period_return(closes(bench), d.date, end),
            )
        )
    return outcomes


def summarize_outcomes(outcomes: Sequence[Outcome]) -> List[Dict[str, Any]]:
    """Per signal at the decision: count, average excess return, share of good calls."""
    groups: Dict[str, List[Outcome]] = {}
    for o in outcomes:
        if o.excess is not None:
            side = "buy/add" if o.decision.action in OPENING else "trim/sell"
            groups.setdefault(f"{side}, {o.decision.signal or 'no score'}", []).append(o)
    return [
        {
            "group": name,
            "count": len(group),
            "mean_excess": mean(o.excess for o in group if o.excess is not None),
            "good_calls": sum(1 for o in group if o.good_call) / len(group),
        }
        for name, group in sorted(groups.items())
    ]


def period_return(close: Optional[pd.Series], start: date, end: date) -> Optional[float]:
    """Percent change from the last close on or before `start` to the last on or before `end`."""
    if close is None or close.empty:
        return None
    series = pd.Series(close.to_numpy(), index=trading_dates(pd.DatetimeIndex(close.index)))
    first = series[: pd.Timestamp(start)].dropna()
    last = series[: pd.Timestamp(end)].dropna()
    if first.empty or last.empty or first.iloc[-1] <= 0:
        return None
    return float((last.iloc[-1] / first.iloc[-1] - 1) * 100)


# ==================== Output ====================


def render_journal(path: Path, checks: Sequence[ThesisCheck], closed: Sequence[Decision]) -> str:
    """Open theses with their status, then the closed and non-opening decisions."""
    rows = []
    for c in checks:
        d, cur = c.decision, c.current or {}
        rows.append(
            [
                d.ticker,
                d.date.isoformat(),
                d.action,
                _fmt(d.price, "{:,.2f}"),
                _fmt(cur.get("price"), "{:,.2f}"),
                _fmt(c.return_pct, "{:+.1f}%"),
                f"{_fmt(d.score, '{:.0f}')} -> {_fmt(cur.get('score'), '{:.0f}')}",
                c.status,
            ]
        )
    sections = [
        Section(
            f"JOURNAL  {path}  ({len(checks)} open)",
            [
                Table(
                    ["Ticker", "Date", "Action", "Entry", "Now", "Return", "Score", "Status"],
                    rows,
                    "lllrrrrl",
                )
                if rows
                else "No open theses."
            ],
        )
    ]
    sections += thesis_sections([c.to_dict() for c in checks])
    if closed:
        sections.append(
            Section(
                "OTHER DECISIONS",
                [
                    f"{d.date.isoformat()}  {d.action:<5} {d.ticker}"
                    + (f"  (closed {d.closed.isoformat()})" if d.closed else "")
                    + (f": {d.thesis}" if d.thesis else "")
                    for d in closed
                ],
            )
        )
    return sections_to_text(sections)


def thesis_sections(checks: Sequence[Dict[str, Any]]) -> List[Section]:
    """
    A THESES TO RECHECK section from `ThesisCheck.to_dict()`s, for the broken
    and warned theses (none if all are OK).
    """
    flagged = [c for c in checks if c["status"] != OK]
    if not flagged:
        return []
    blocks: List[Any] = []
    for c in flagged:
        d = c["decision"]
        if blocks:
            blocks.append("")
        new = " (new)" if c.get("new") else ""
        blocks.append(f"{d['ticker']}  {c['status'].upper()}{new}  ({d['action']} {d['date']})")
        if d.get("thesis"):
            blocks.append(f"  thesis: {d['thesis']}")
        if d.get("exit_if"):
            blocks.append(f"  exit if: {d['exit_if']}")
        blocks += [f"  - {reason}" for reason in c["broken"] + c["warnings"]]
    return [Section("THESES TO RECHECK", blocks)]


def render_look_back(outcomes: Sequence[Outcome]) -> str:
    rows = [
        [
            o.decision.date.isoformat(),
            o.decision.action,
            o.decision.ticker,
            o.decision.signal or "",
            o.end.isoformat(),
            _fmt(o.ticker_return, "{:+.1f}%"),
            o.benchmark,
            _fmt(o.benchmark_return, "{:+.1f}%"),
            _fmt(o.excess, "{:+.1f}%"),
            {True: "yes", False: "no", None: ""}[o.good_call],
        ]
        for o in outcomes
    ]
    summary = [
        [
            g["group"],
            str(g["count"]),
            f"{g['mean_excess']:+.1f}%",
            f"{g['good_calls']:.0%}",
        ]
        for g in summarize_outcomes(outcomes)
    ]
    headers = ["Date", "Action", "Ticker", "Signal", "To", "Return", "Bench", "Bench ret"]
    sections = [
        Section(
            f"LOOK-BACK  ({len(outcomes)} decisions)",
            [Table([*headers, "Excess", "Good call"], rows, "llllrrlrrl")]
            if rows
            else ["No decisions in the journal yet."],
        )
    ]
    if summary:
        sections.append(
            Section(
                "BY SIGNAL AT THE TIME",
                [Table(["Decisions", "Count", "Avg excess", "Good calls"], summary, "lrrr")],
            )
        )
    sections.append(
        Section(
            "NOTES",
            [
                "Close on the decision date to the close when it was sold, or today; "
                "no dividends, costs or currency effects.",
                "A good call is a buy or add that beat its benchmark, or a trim or sell "
                "that lagged it.",
                "Few decisions say little: read the averages as anecdotes until there are dozens.",
            ],
        )
    )
    return sections_to_text(sections)


def _return_pct(decision: Decision, current: Optional[Row]) -> Optional[float]:
    price = (current or {}).get("price")
    if not price or not decision.price:
        return None
    if decision.currency and current and current.get("currency") != decision.currency:
        return None
    return float((price / decision.price - 1) * 100)


def _toml(value: Any) -> str:
    """A string, number or list of strings as a TOML value."""
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_string(str(v)) for v in value) + "]"
    if not math.isfinite(value):
        raise ValueError(f"Not a usable number: {value}")
    return repr(float(value))


def _text(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _date(value: Any) -> Optional[date]:
    # A TOML datetime is a date subclass that doesn't compare with plain dates
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _fmt(value: Optional[float], pattern: str) -> str:
    return "" if value is None else pattern.format(value)
