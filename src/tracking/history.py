"""
Score History

Every scoring run (`report`, `score`, `vet`, `screen` stage 2, `changes`)
appends one row per ticker to `<data>/_history/scores.csv`, keeping one row
per ticker, preset and day (the latest run that day wins).

The score recorded is the composite with the standard valuation cutoffs.
`vet` also rescales P/E against peers, but that score isn't stored, so rows
from every command compare like with like.
"""

import csv
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..scoring.scorer import ScoringResult
from ..vetting.red_flags import RedFlag
from ..vetting.verdict import current_price

HISTORY_COLUMNS = [
    "date",
    "ticker",
    "preset",
    "source",
    "score",
    "technical",
    "fundamental",
    "risk",
    "valuation",
    "signal",
    "confidence",
    "price",
    "currency",
    "red_flags",
    "flags",
]
DIMENSIONS = ("technical", "fundamental", "risk", "valuation")
_NUMERIC = {"score", "price", *DIMENSIONS}
_FLAG_SEPARATOR = " | "

Row = Dict[str, Any]


def history_path(data_dir: str = "data") -> Path:
    return Path(data_dir) / "_history" / "scores.csv"


def history_row(
    report: Dict[str, Any],
    scoring: Optional[ScoringResult],
    source: str,
    red_flags: Optional[List[RedFlag]] = None,
    today: Optional[date] = None,
) -> Optional[Row]:
    """
    One history row from a report and its score. None if nothing was scored or
    there's no price: an unknown symbol still gets a meaningless score.
    """
    price = current_price(report)
    if scoring is None or price is None:
        return None
    if red_flags is None:
        from ..vetting.red_flags import find_red_flags

        red_flags = find_red_flags(report)
    # One rule can fire several times (e.g. one "Stale data" flag per warning)
    titles = list(dict.fromkeys(f.title for f in red_flags))

    def _dim(name: str) -> Optional[float]:
        dim = getattr(scoring, name)
        return round(dim.score, 1) if dim is not None else None

    return {
        "date": (today or date.today()).isoformat(),
        "ticker": scoring.ticker.upper(),
        "preset": scoring.config_name,
        "source": source,
        "score": round(scoring.composite_score, 1),
        **{name: _dim(name) for name in DIMENSIONS},
        "signal": scoring.signal,
        "confidence": scoring.confidence,
        "price": round(price, 4),
        "currency": (report.get("info") or {}).get("currency"),
        "red_flags": len(red_flags),
        "flags": _FLAG_SEPARATOR.join(titles),
    }


def record_scores(rows: Iterable[Optional[Row]], data_dir: str = "data") -> Optional[Path]:
    """Append rows, replacing any row for the same date, ticker and preset."""
    new = [row for row in rows if row]
    if not new:
        return None
    path = history_path(data_dir)
    keys = {_key(row) for row in new}
    kept = [row for row in load_history(data_dir) if _key(row) not in keys]
    merged = sorted(kept + new, key=lambda r: r["date"])  # stable: run order within a day

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: "" if v is None else v for k, v in row.items()} for row in merged)
    os.replace(tmp, path)
    return path


def load_history(
    data_dir: str = "data",
    ticker: Optional[str] = None,
    preset: Optional[str] = None,
) -> List[Row]:
    """History rows, oldest first, optionally for one ticker and/or preset."""
    path = history_path(data_dir)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = [_parse(raw) for raw in csv.DictReader(f)]
    return [
        row
        for row in rows
        if (ticker is None or row["ticker"] == ticker.upper())
        and (preset is None or row["preset"] == preset)
    ]


def flag_titles(row: Optional[Row]) -> List[str]:
    if not row or not row.get("flags"):
        return []
    return [t for t in str(row["flags"]).split(_FLAG_SEPARATOR) if t]


def _key(row: Row) -> tuple[str, str, str]:
    return row["date"], row["ticker"], row["preset"]


def _parse(raw: Dict[str, str]) -> Row:
    row: Row = {}
    for column in HISTORY_COLUMNS:
        value = (raw.get(column) or "").strip()
        if column in _NUMERIC:
            row[column] = float(value) if value else None
        elif column == "red_flags":
            row[column] = int(value) if value else 0
        else:
            row[column] = value or None
    return row
