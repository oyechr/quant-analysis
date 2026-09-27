"""
Rendering for `quant vet`

Builds the sections once from `VetResult.to_dict()` as lines and tables,
then formats them for the terminal or as Markdown.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from ..markets import benchmark_name
from ..utils.report import get_currency_symbol

WIDTH = 70

_SEVERITY_MARK = {"high": "!!", "medium": "! ", "low": "- "}
_BASIS_LABEL = {
    "yahoo_industry": "Yahoo industry list, similar size",
    "yahoo_industry_sector": "Yahoo industry list topped up from its sector list, similar size",
    "yahoo_sector": "Yahoo sector list, similar size",
    "explicit": "your --peers",
}
_PEAD_LABEL = {
    "strong_buy": "strongly positive",
    "buy": "positive",
    "slight_positive": "slightly positive",
    "neutral": "neutral",
    "slight_negative": "slightly negative",
    "sell": "negative",
    "strong_sell": "strongly negative",
}
_DIM_ABBR = {"technical": "Tech", "fundamental": "Fund", "risk": "Risk", "valuation": "Val"}
_ACTION_LABEL = {
    "new": "new position",
    "add": "added",
    "trim": "trimmed",
    "hold": "held",
    "exit": "exited",
}


@dataclass
class Table:
    headers: List[str]
    rows: List[List[str]]
    align: str = ""  # per column: "l" or "r"; default left for the first, right for the rest


Block = Union[str, Table]


@dataclass
class Section:
    title: str
    blocks: List[Block] = field(default_factory=list)


def build_sections(data: Dict[str, Any], brief: bool = False) -> List[Section]:
    header = data.get("header") or {}
    sym = get_currency_symbol(header.get("currency") or "USD")
    steps = Section("NEXT STEPS", [f"-> {s}" for s in data.get("next_steps") or []])
    if brief:
        return [_header_section(data, header, sym), steps]
    return [
        _header_section(data, header, sym),
        _red_flags_section(data),
        _peers_section(data),
        _signals_section(data),
        _funds_section(data),
        _verdict_section(data, sym),
        _strengths_section(data),
        steps,
    ]


def render_text(data: Dict[str, Any], brief: bool = False) -> str:
    out: List[str] = []
    for i, section in enumerate(build_sections(data, brief)):
        if i == 0:
            out += ["=" * WIDTH, f"  {section.title}", "=" * WIDTH]
        else:
            out += ["", "-" * WIDTH, f"  {section.title}", "-" * WIDTH]
        for block in section.blocks:
            if isinstance(block, Table):
                out += ["  " + line for line in _text_table(block)]
            else:
                out.append(f"  {block}" if block else "")
    out.append("")
    return "\n".join(out)


def render_markdown(data: Dict[str, Any]) -> str:
    out: List[str] = []
    for i, section in enumerate(build_sections(data)):
        out += [f"# {section.title}" if i == 0 else f"## {section.title.title()}", ""]
        for block in section.blocks:
            if isinstance(block, Table):
                out += [*_markdown_table(block), ""]
            elif block:
                out.append(block if block.startswith(("-", "|")) else f"- {block.strip()}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ==================== Sections ====================


def _header_section(data: Dict[str, Any], header: Dict[str, Any], sym: str) -> Section:
    title = f"VET: {data.get('ticker')}"
    if header.get("name"):
        title += f"  {header['name']}"
    dims = header.get("dimensions") or {}
    dim_text = "  ".join(
        f"{_DIM_ABBR.get(k, k.title())} {v:.0f}" for k, v in dims.items() if v is not None
    )
    blocks: List[Block] = [*_verdict_lines(data.get("verdict") or {}, sym), ""]
    blocks += [
        f"{header.get('sector') or 'N/A'} / {header.get('industry') or 'N/A'}",
        f"Price: {_money(header.get('price'), sym)}   Preset: {data.get('preset')}",
    ]
    if dim_text:
        blocks.append(f"Score {_num(header.get('score'), 0)}/100:  {dim_text}")
    if data.get("next_earnings"):
        blocks.append(f"Next earnings: {data['next_earnings']}")
    return Section(title, blocks)


def _verdict_lines(verdict: Dict[str, Any], sym: str) -> List[str]:
    if not verdict:
        return []
    lines = [f"VERDICT: {verdict['call'].upper()}"]
    if verdict.get("reasons"):
        lines.append("  " + " | ".join(verdict["reasons"]))
    flip = verdict.get("flip")
    if flip:
        word = "at or below" if flip["direction"] == "up" else "at or above"
        lines.append(
            f"  Would turn {flip['signal']} {word} {_money(flip['price'], sym)} "
            f"({_pct(flip.get('change_pct'))}), all else equal"
        )
    return lines


def _red_flags_section(data: Dict[str, Any]) -> Section:
    flags = data.get("red_flags") or []
    if not flags:
        return Section("RED FLAGS", ["None found"])
    return Section(
        "RED FLAGS",
        [
            f"{_SEVERITY_MARK.get(f['severity'], '- ')} [{f['severity']}] {f['title']}: {f['detail']}"
            for f in flags
        ],
    )


def _peers_section(data: Dict[str, Any]) -> Section:
    peers = data.get("peer_valuation") or {}
    if not peers or not peers.get("peers"):
        missing = peers.get("missing") if peers else None
        note = "No peers with data"
        if missing:
            note += f" (no data for {', '.join(missing)})"
        return Section("PEER VALUATION", [note])

    basis = _BASIS_LABEL.get(peers.get("basis") or "", peers.get("basis"))
    group = f" in {peers['group']}" if peers.get("group") else ""
    names = ", ".join(peers["peers"][:8]) + (" ..." if len(peers["peers"]) > 8 else "")
    blocks: List[Block] = [f"{len(peers['peers'])} peers ({basis}{group}): {names}"]
    if peers.get("missing"):
        blocks.append(f"No data for: {', '.join(peers['missing'])}")

    rows = []
    for metric in (peers.get("metrics") or {}).values():
        cheap = metric.get("cheapness")
        rows.append(
            [
                metric["label"],
                _num(metric.get("value"), 1),
                _num(metric.get("median"), 1),
                f"{cheap:.0f}" if cheap is not None else "N/A",
                str(metric.get("n", 0)),
                _cheapness_label(cheap),
            ]
        )
    blocks.append(Table(["Metric", "Value", "Median", "Cheaper than %", "n", ""], rows, "lrrrrl"))
    blocks.append("'Cheaper than %': share of peers that are more expensive on that metric")
    return Section("PEER VALUATION", blocks)


def _signals_section(data: Dict[str, Any]) -> Section:
    signals = data.get("signals") or {}
    blocks: List[Block] = []
    rs = signals.get("relative_strength")
    if rs:
        bench = benchmark_name(rs.get("benchmark")) if rs.get("benchmark") else "no benchmark"
        blocks.append(
            f"Relative strength: {rs.get('rs_rating')}/99 vs {bench}  "
            f"({_pct(rs.get('relative_return_pct'))} weighted excess return)  "
            f"{rs.get('interpretation', '')}"
        )
    pead = signals.get("pead")
    if pead:
        sue = pead.get("sue")
        streak = pead.get("streak")
        direction = pead.get("streak_direction")
        noun = (
            {"beat": "beats", "miss": "misses"}.get(direction or "", "")
            if streak != 1
            else direction
        )
        streak_text = f", {streak} {noun} in a row" if streak else ""
        drift = pead.get("post_earnings_return_pct")
        drift_text = f", {_pct(drift)} since report" if drift is not None else ""
        blocks.append(
            f"Post-earnings drift: {_PEAD_LABEL.get(pead.get('signal') or '', pead.get('signal'))}"
            f" (SUE {_num(sue, 2)}{streak_text}{drift_text})"
        )
        blocks.append(f"  {pead.get('interpretation', '')}")
    return Section("SIGNALS", blocks or ["No signal data"])


def _funds_section(data: Dict[str, Any]) -> Section:
    funds = data.get("fund_activity") or {}
    if not funds.get("cache_found"):
        return Section(
            "FUND ACTIVITY (13F)",
            ["No 13F cache. Run `quant discover` to fetch tracked funds' filings."],
        )
    positions = funds.get("positions") or []
    if not positions:
        return Section(
            "FUND ACTIVITY (13F)",
            [f"None of the {funds.get('funds_checked', 0)} tracked funds hold it"],
        )
    rows = [
        [
            p["fund"],
            _ACTION_LABEL.get(p["action"], p["action"]),
            _big(p.get("shares")),
            p.get("period") or "",
        ]
        for p in positions
    ]
    blocks: List[Block] = [
        f"{len(positions)} of {funds.get('funds_checked', 0)} tracked funds",
        Table(["Fund", "Latest action", "Shares", "As of"], rows, "llrl"),
    ]
    if any(p.get("matched_on") == "name" for p in positions):
        blocks.append(
            "Some positions matched by issuer name (e.g. a US ADR or another share class)"
        )
    return Section("FUND ACTIVITY (13F)", blocks)


def _verdict_section(data: Dict[str, Any], sym: str) -> Section:
    fv = data.get("fair_value") or {}
    price = fv.get("current_price")
    upside = fv.get("upside_pct") or {}
    blocks: List[Block] = []

    rows = []
    analysts = fv.get("analysts") or {}
    if analysts:
        count = f" (n={analysts['count']})" if analysts.get("count") else ""
        rows.append(
            [
                f"Analyst target mean{count}",
                _money(analysts["mean"], sym),
                _pct(upside.get("analyst_mean")),
            ]
        )
        if analysts.get("low") is not None and analysts.get("high") is not None:
            rows.append(
                [
                    "Analyst target range",
                    f"{_money(analysts['low'], sym)} - {_money(analysts['high'], sym)}",
                    "",
                ]
            )
    mc = fv.get("monte_carlo") or {}
    if mc:
        rows.append(
            [
                "Monte Carlo 10-90%",
                f"{_money(mc.get('ci_10'), sym)} - {_money(mc.get('ci_90'), sym)}",
                "",
            ]
        )
        rows.append(
            ["Monte Carlo median", _money(mc.get("ci_50"), sym), _pct(upside.get("mc_median"))]
        )
    if fv.get("dcf") is not None:
        rows.append(["DCF", _money(fv["dcf"], sym), _pct(upside.get("dcf"))])
    if fv.get("ddm") is not None:
        rows.append(["DDM", _money(fv["ddm"], sym), _pct(upside.get("ddm"))])
    if rows:
        blocks.append(f"Fair value (price {_money(price, sym)}):")
        blocks.append(Table(["Model", "Value/share", "vs price"], rows, "lrr"))
        if analysts.get("recommendation"):
            blocks.append(
                f"Analyst consensus: {str(analysts['recommendation']).replace('_', ' ')}"
                + (
                    f" ({analysts['recommendation_mean']:.1f} on a 1 = strong buy to 5 = sell scale)"
                    if analysts.get("recommendation_mean") is not None
                    else ""
                )
            )
        if mc.get("probability_undervalued") is not None:
            blocks.append(f"P(undervalued) per Monte Carlo: {mc['probability_undervalued']:.0%}")
        dcf = fv.get("dcf_assumptions") or {}
        if dcf.get("growth_start") is not None and dcf.get("wacc") is not None:
            line = (
                f"DCF: FCF growth {dcf['growth_start']:+.1f}% fading to "
                f"{dcf.get('terminal_growth') or 0:.1f}% over {dcf.get('years')}y, "
                f"discounted at {dcf['wacc']:.1f}%"
            )
            if dcf.get("implied_growth") is not None:
                line += f"; the price implies {dcf['implied_growth']:+.1f}% starting growth"
            blocks.append(line)
        if fv.get("currency_note"):
            blocks.append(fv["currency_note"])
    else:
        blocks.append("No model valuations available")

    flips = data.get("signal_flips") or {}
    if flips:
        blocks.append("")
        blocks.append(
            f"Signal is {flips.get('current_signal')}. Holding everything but price constant:"
        )
        for direction in ("up", "down"):
            flip = flips.get(direction)
            if not flip:
                continue
            if flip.get("price") is None:
                blocks.append(f"  {flip['signal']}: {flip.get('note')}")
            else:
                word = "at or below" if direction == "up" else "at or above"
                blocks.append(
                    f"  {flip['signal']} {word} {_money(flip['price'], sym)} ({_pct(flip.get('change_pct'))})"
                )

    levels = data.get("trade_levels") or {}
    for scenario in ("bullish", "bearish"):
        lv = levels.get(scenario)
        if not lv or lv.get("target") is None:
            continue
        zone = lv.get("entry_zone") or {}
        entry = _money(zone.get("low"), sym)
        if zone.get("high") and zone.get("high") != zone.get("low"):
            entry += f"-{_money(zone.get('high'), sym)}"
        if scenario == "bullish":
            blocks.append("")
        blocks.append(
            f"{scenario.title()}: entry {entry}, target {_money(lv.get('target'), sym)}, "
            f"stop {_money(lv.get('stop_loss'), sym)} (R/R {_num(lv.get('reward_risk_ratio'), 2)})"
        )
    return Section("WHAT WOULD CHANGE THE VERDICT", blocks)


def _strengths_section(data: Dict[str, Any]) -> Section:
    blocks: List[Block] = [f"+ {s}" for s in (data.get("strengths") or [])[:5]]
    blocks += [f"- {c}" for c in (data.get("concerns") or [])[:5]]
    return Section("STRENGTHS / CONCERNS", blocks or ["None noted"])


# ==================== Formatting ====================


def _text_table(table: Table) -> List[str]:
    cols = len(table.headers)
    widths = [max(len(str(row[i])) for row in [table.headers, *table.rows]) for i in range(cols)]
    align = table.align or ("l" + "r" * (cols - 1))

    def fmt(row: List[str]) -> str:
        cells = [
            str(cell).ljust(widths[i]) if align[i] == "l" else str(cell).rjust(widths[i])
            for i, cell in enumerate(row)
        ]
        return "  ".join(cells).rstrip()

    return [fmt(table.headers), "  ".join("-" * w for w in widths)] + [fmt(r) for r in table.rows]


def _markdown_table(table: Table) -> List[str]:
    align = table.align or ("l" + "r" * (len(table.headers) - 1))
    sep = ["---:" if a == "r" else "---" for a in align]
    lines = [
        "| " + " | ".join(h or " " for h in table.headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in table.rows]
    return lines


def _cheapness_label(cheapness: Optional[float]) -> str:
    if cheapness is None:
        return ""
    if cheapness >= 75:
        return "cheap vs peers"
    if cheapness <= 25:
        return "rich vs peers"
    return ""


def _num(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except TypeError, ValueError:
        return str(value)


def _money(value: Any, sym: str) -> str:
    if value is None:
        return "N/A"
    return f"{sym}{float(value):,.2f}"


def _pct(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value):+.1f}%"


def _big(value: Any) -> str:
    if not value:
        return "-"
    value = float(value)
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= size:
            return f"{value / size:.1f}{unit}"
    return f"{value:.0f}"
