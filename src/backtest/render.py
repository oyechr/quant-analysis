"""
Rendering and saving for `quant backtest`
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..vetting.render import Section, Table, sections_to_markdown, sections_to_text
from .engine import BacktestResult
from .stats import summarize

SIGNAL_LABELS = {
    "composite": "Composite (price-only)",
    "technical": "Technical score",
    "risk": "Risk score",
    "momentum": "Momentum 12-1",
    "low_vol": "Low volatility",
}

CAVEATS = [
    "Fundamental and valuation scores are not tested: Yahoo's statements are restated "
    "and undated, so they can't be used as of a past date. The composite here is the "
    "technical and risk dimensions only, scored with the preset's Buy/Hold/Sell bands.",
    "Survivorship bias: the universe is today's constituents, so companies that were "
    "dropped or delisted along the way are missing. This flatters every signal a little.",
    "Trades at the signal day's close with no costs; returns include dividends.",
    "Overlapping 3- and 6-month windows: intervals use Newey-West errors, but a few "
    "years of months is still a small sample.",
]


def backtest_to_dict(result: BacktestResult) -> Dict[str, Any]:
    obs = result.observations
    return {
        "meta": {
            "universe": result.universe,
            "preset": result.preset,
            "years": result.years,
            "horizons": list(result.horizons),
            "first_month": result.months[0] if result.months else None,
            "last_month": result.months[-1] if result.months else None,
            "tickers": result.tickers,
            "observations": len(obs),
            "generated_at": result.generated_at,
        },
        "summary": summarize(obs, result.horizons) if not obs.empty else None,
        "errors": result.errors,
    }


def build_sections(data: Dict[str, Any]) -> List[Section]:
    meta = data["meta"]
    horizons = [f"{h}m" for h in meta["horizons"]]
    sections = [
        Section(
            f"BACKTEST  {meta['universe']}  {meta['first_month']} to {meta['last_month']}",
            [
                f"{meta['tickers']} tickers, {meta['observations']} ticker-months, "
                f"preset {meta['preset']}",
                "Returns are relative to each ticker's home benchmark; "
                "* marks a 95% interval that excludes zero",
            ],
        )
    ]
    summary = (data.get("summary") or {}).get("excess")
    if not summary:
        sections.append(Section("RESULTS", ["No observations: check the errors below."]))
    else:

        def table(stat: str, fmt, kind: str = "excess") -> Table:
            signals = data["summary"][kind]["signals"]
            rows = [
                [SIGNAL_LABELS.get(name, name), *(fmt(by_h[h][stat]) for h in horizons)]
                for name, by_h in signals.items()
            ]
            return Table(["Signal", *horizons], rows)

        sections += [
            Section(
                "RANK IC (Spearman, mean over months)",
                [table("ic", lambda ci: _ci(ci, "{:+.3f}"))],
            ),
            Section(
                "QUINTILE SPREAD (top fifth minus bottom fifth)",
                [table("spread", lambda ci: _ci(ci, "{:+.1%}"))],
            ),
            Section(
                "HIT RATE (months the top fifth beat the bottom fifth)",
                [table("hit_rate", lambda ci: _ci(ci, "{:.0%}", centre=0.5))],
            ),
        ]
        if "alpha" in data["summary"]:
            sections.append(
                Section(
                    "BETA-ADJUSTED (returns net of each stock's beta x benchmark)",
                    [
                        "Rank IC",
                        table("ic", lambda ci: _ci(ci, "{:+.3f}"), "alpha"),
                        "",
                        "Quintile spread",
                        table("spread", lambda ci: _ci(ci, "{:+.1%}"), "alpha"),
                        "",
                        "Where this differs from the tables above, the signal mostly picks",
                        "stocks that move more or less than the market, not better ones.",
                    ],
                )
            )
        sections += [
            Section(
                "SIGNAL BANDS (price-only composite)",
                [
                    Table(
                        ["Band", "Score", "Share", *horizons],
                        [_band_row(row, horizons) for row in summary["bands"]],
                        "llr" + "r" * len(horizons),
                    ),
                    "",
                    "Each cell: mean return vs benchmark per month, then the share of",
                    "ticker-months that beat it. Useful bands rise from Strong Sell to Strong Buy.",
                ],
            ),
        ]

    notes: List[Union[str, Table]] = list(CAVEATS)
    if data.get("errors"):
        failed = [f"{t} ({e})" for t, e in data["errors"].items()]
        notes.append(f"Not tested: {', '.join(failed[:10])}{' ...' if len(failed) > 10 else ''}")
    sections.append(Section("CAVEATS", notes))
    return sections


def render_text(data: Dict[str, Any]) -> str:
    return sections_to_text(build_sections(data))


def render_markdown(data: Dict[str, Any]) -> str:
    return sections_to_markdown(build_sections(data))


def save_backtest(result: BacktestResult, data: Dict[str, Any], output_dir: str) -> List[Path]:
    """Summary (JSON, Markdown) and every observation (CSV) under <output_dir>/_backtests/."""
    out = Path(output_dir) / "_backtests"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = out / f"backtest_{_slug(result.universe)}_{result.years}y_{stamp}"
    paths = [base.with_suffix(".json"), base.with_suffix(".md"), Path(f"{base}_observations.csv")]
    paths[0].write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    paths[1].write_text(render_markdown(data), encoding="utf-8")
    result.observations.to_csv(paths[2], index=False)
    return paths


def _ci(ci: Optional[Dict[str, Any]], fmt: str, centre: float = 0.0) -> str:
    if not ci:
        return "n/a"
    star = "*" if ci["low"] > centre or ci["high"] < centre else " "
    return f"{fmt.format(ci['mean'])} [{fmt.format(ci['low'])}, {fmt.format(ci['high'])}]{star}"


def _band_row(row: Dict[str, Any], horizons: List[str]) -> List[str]:
    cells = [row["band"], row["range"], f"{row['share']:.0%}" if row["share"] is not None else ""]
    for h in horizons:
        cell = row[h]
        mean = cell["mean"]
        if mean is None:
            cells.append("n/a")
            continue
        star = "*" if mean["low"] > 0 or mean["high"] < 0 else " "
        cells.append(f"{mean['mean']:+.1%}{star} ({cell['beat']:.0%})")
    return cells


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "custom"
