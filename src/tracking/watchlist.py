"""
Watchlist

Tickers you are following, kept in `watchlist.toml` in the repo root
(gitignored: it's personal). One table per ticker:

    ["EQNR.OL"]
    thesis = "Cheap vs peers if oil holds above $70"
    added = 2026-10-22
    target = 450.0
    stop = 380.0

Target and stop are prices in the listing currency. The file is meant to be
editable by hand; `quant watchlist add/rm` rewrite it in the same layout.
"""

import json
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_WATCHLIST = "watchlist.toml"


@dataclass
class WatchItem:
    ticker: str
    added: date
    thesis: Optional[str] = None
    target: Optional[float] = None
    stop: Optional[float] = None


def load_watchlist(path: Path) -> Dict[str, WatchItem]:
    """Watchlist entries by ticker, in file order; empty if the file doesn't exist."""
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Can't read {path}: {e}") from e

    items: Dict[str, WatchItem] = {}
    for ticker, entry in data.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: '{ticker}' should be a table, e.g. [\"{ticker}\"]")
        added = entry.get("added")
        items[ticker.upper()] = WatchItem(
            ticker=ticker.upper(),
            added=added if isinstance(added, date) else date.today(),
            thesis=entry.get("thesis") or None,
            target=_price(entry.get("target")),
            stop=_price(entry.get("stop")),
        )
    return items


def save_watchlist(items: Dict[str, WatchItem], path: Path) -> None:
    lines: List[str] = []
    for item in items.values():
        lines.append(f"[{_toml_string(item.ticker)}]")
        if item.thesis:
            lines.append(f"thesis = {_toml_string(item.thesis)}")
        lines.append(f"added = {item.added.isoformat()}")
        if item.target is not None:
            lines.append(f"target = {item.target!r}")
        if item.stop is not None:
            lines.append(f"stop = {item.stop!r}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def add_to_watchlist(
    path: Path,
    tickers: Iterable[str],
    thesis: Optional[str] = None,
    target: Optional[float] = None,
    stop: Optional[float] = None,
    today: Optional[date] = None,
) -> tuple[List[str], List[str]]:
    """
    Add tickers, or update the given fields of ones already listed (their
    added date is kept). Returns (added, updated).
    """
    items = load_watchlist(path)
    added: List[str] = []
    updated: List[str] = []
    for ticker in dict.fromkeys(t.strip().upper() for t in tickers if t.strip()):
        item = items.get(ticker)
        if item is None:
            items[ticker] = WatchItem(ticker, today or date.today(), thesis, target, stop)
            added.append(ticker)
            continue
        if thesis is not None:
            item.thesis = thesis or None
        if target is not None:
            item.target = target
        if stop is not None:
            item.stop = stop
        updated.append(ticker)
    save_watchlist(items, path)
    return added, updated


def remove_from_watchlist(path: Path, tickers: Iterable[str]) -> tuple[List[str], List[str]]:
    """Remove tickers. Returns (removed, not_found)."""
    items = load_watchlist(path)
    removed: List[str] = []
    missing: List[str] = []
    for ticker in dict.fromkeys(t.strip().upper() for t in tickers if t.strip()):
        if items.pop(ticker, None) is None:
            missing.append(ticker)
        else:
            removed.append(ticker)
    if removed:
        save_watchlist(items, path)
    return removed, missing


def _toml_string(value: str) -> str:
    # A JSON string (escapes and all) is a valid TOML basic string
    return json.dumps(value, ensure_ascii=False)


def _price(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
