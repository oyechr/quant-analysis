"""
Rendering for `quant review`

Leads with the action table (one row per holding), then the portfolio-level
view, then details for every holding whose action isn't Hold. Works from
`PortfolioReview.to_dict()` and reuses the vet renderer's layout.
"""

from typing import Any, Dict, List

from ..vetting.render import (
    Block,
    Section,
    Table,
    sections_to_markdown,
    sections_to_text,
)

REASON_WIDTH = 60
TOP_PAIRS = 8

CAVEATS = [
    "Rule-based suggestions from free Yahoo data, not advice.",
    "Taxes are ignored apart from the AF/ASK note; selling outside an ASK realizes gains.",
    "Targets are inverse-volatility (risk-parity) weights over the holdings with price history.",
    "DCF limits from `quant vet` apply (cyclicals at a capex peak look expensive).",
]


def build_sections(data: Dict[str, Any]) -> List[Section]:
    return [
        _summary_section(data),
        _portfolio_section(data),
        _details_section(data),
        _notes_section(data),
    ]


def render_text(data: Dict[str, Any]) -> str:
    return sections_to_text(build_sections(data))


def render_markdown(data: Dict[str, Any]) -> str:
    return sections_to_markdown(build_sections(data))


# ==================== Sections ====================


def _summary_section(data: Dict[str, Any]) -> Section:
    summary = data.get("summary") or {}
    ccy = data.get("base_currency") or ""
    actions = summary.get("actions") or {}
    title = f"PORTFOLIO REVIEW  {summary.get('holdings', 0)} holdings, preset {data.get('preset')}"
    blocks: List[Block] = [
        "  ".join(f"{action.upper()} {n}" for action, n in actions.items()),
        f"Value {_money(summary.get('total_value'), ccy)}"
        + (
            f"   Gain {_pct(summary.get('gain_pct'))}"
            if summary.get("gain_pct") is not None
            else ""
        )
        + (
            f"   Weighted score {summary['weighted_score']:.0f}"
            if summary.get("weighted_score") is not None
            else ""
        ),
        "",
    ]
    rows = []
    for h in data.get("holdings") or []:
        checked = h["action"] != "Check"
        verdict = ((h.get("verdict") or {}).get("call") or "") if checked else ""
        if h.get("is_fund") and checked:
            verdict = "(fund)"
        rows.append(
            [
                h["ticker"],
                h["action"].upper(),
                _share(h.get("weight")),
                _share(h.get("target_weight")),
                _pct(h.get("gain_pct"), 0),
                f"{h['score']:.0f}" if h.get("score") is not None and checked else "",
                verdict,
                _short((h.get("reasons") or [""])[0]),
            ]
        )
    blocks.append(
        Table(
            ["Ticker", "Action", "Weight", "Target", "Gain", "Score", "Verdict", "Main reason"],
            rows,
            "llrrrrll",
        )
    )
    return Section(title, blocks)


def _portfolio_section(data: Dict[str, Any]) -> Section:
    summary = data.get("summary") or {}
    blocks: List[Block] = []
    facts = []
    if summary.get("weighted_beta") is not None:
        facts.append(f"Weighted beta {summary['weighted_beta']:.2f}")
    if summary.get("diversification_score") is not None:
        facts.append(
            f"Diversification {summary['diversification_score']}/100 "
            f"(average correlation {summary.get('average_correlation', 0):.2f})"
        )
    largest = summary.get("largest") or {}
    if largest.get("weight") is not None:
        facts.append(f"Largest {largest['ticker']} {largest['weight']:.1%}")
    if facts:
        blocks.append("   ".join(facts))

    for flag in summary.get("concentration_flags") or []:
        blocks.append(f"!  {flag}")

    sectors = summary.get("by_sector") or []
    currencies = summary.get("by_currency") or []
    if sectors:
        blocks += ["", "By sector: " + _groups(sectors)]
    if currencies:
        blocks.append("By currency: " + _groups(currencies))

    pairs = summary.get("correlated_pairs") or []
    if pairs:
        blocks += ["", f"Move together (daily-return correlation >= 0.80), {len(pairs)} pair(s):"]
        blocks += [
            f"  {p['pair'][0]} / {p['pair'][1]}  {p['correlation']:.2f}" for p in pairs[:TOP_PAIRS]
        ]
        if len(pairs) > TOP_PAIRS:
            blocks.append(f"  ... and {len(pairs) - TOP_PAIRS} more (see --json)")
    return Section("PORTFOLIO", blocks or ["No holdings could be valued"])


def _details_section(data: Dict[str, Any]) -> Section:
    flagged = [h for h in data.get("holdings") or [] if h["action"] != "Hold"]
    if not flagged:
        return Section("DETAILS", ["Every holding is a Hold"])
    blocks: List[Block] = []
    for h in flagged:
        accounts = ", ".join(h.get("accounts") or [])
        blocks.append(
            f"{h['action'].upper()} {h['ticker']}  {h.get('name') or ''}"
            + (f"  [{accounts}]" if accounts else "")
        )
        for reason in h.get("reasons") or []:
            blocks.append(f"  - {reason}")
        price = h.get("price")
        if price is not None:
            line = f"  Price {price:,.2f} {h.get('listing_currency') or ''}"
            if h.get("cost_basis"):
                line += f", cost {h['cost_basis']:,.2f} {h.get('cost_currency') or ''}"
            blocks.append(line)
        flip = (h.get("verdict") or {}).get("flip")
        if flip and flip.get("price") is not None:
            word = "at or below" if flip["direction"] == "up" else "at or above"
            blocks.append(
                f"  Signal turns {flip['signal']} {word} {flip['price']:,.2f} "
                f"({_pct(flip.get('change_pct'))})"
            )
        flags = [f for f in h.get("red_flags") or [] if f.get("severity") in ("high", "medium")]
        if flags:
            blocks.append("  Red flags: " + "; ".join(f["title"] for f in flags))
        blocks.append("")
    blocks.append("For the full picture on one holding: quant vet TICKER")
    return Section("DETAILS", blocks)


def _notes_section(data: Dict[str, Any]) -> Section:
    blocks: List[Block] = list(CAVEATS)
    unmapped = data.get("unmapped") or []
    if unmapped:
        blocks.append(
            f"No ticker for {len(unmapped)} name(s), left out: {', '.join(unmapped)}. "
            "Add them to portfolio/tickers.csv and rerun import-portfolio."
        )
    return Section("NOTES", blocks)


# ==================== Formatting ====================


def _groups(rows: List[Dict[str, Any]], limit: int = 6) -> str:
    text = ", ".join(f"{r['name']} {r['weight']:.0%}" for r in rows[:limit])
    return text + (", ..." if len(rows) > limit else "")


def _share(value: Any) -> str:
    return f"{float(value):.1%}" if value is not None else ""


def _pct(value: Any, decimals: int = 1) -> str:
    return f"{float(value):+.{decimals}f}%" if value is not None else ""


def _money(value: Any, ccy: str) -> str:
    return f"{float(value):,.0f} {ccy}" if value is not None else "N/A"


def _short(text: str) -> str:
    return text if len(text) <= REASON_WIDTH else text[: REASON_WIDTH - 3] + "..."
