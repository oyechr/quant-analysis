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
    "Risk, beta and correlations use two years of weekly returns in the base currency.",
    "Factor tilts describe the stocks held (weighted medians); they are not regression loadings.",
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
                _share(h.get("risk_share")),
                _share(h.get("target_weight")),
                _pct(h.get("gain_pct"), 0),
                f"{h['score']:.0f}" if h.get("score") is not None and checked else "",
                verdict,
                _short((h.get("reasons") or [""])[0]),
            ]
        )
    blocks.append(
        Table(
            [
                "Ticker",
                "Action",
                "Weight",
                "Risk",
                "Target",
                "Gain",
                "Score",
                "Verdict",
                "Main reason",
            ],
            rows,
            "llrrrrrll",
        )
    )
    return Section(title, blocks)


def _portfolio_section(data: Dict[str, Any]) -> Section:
    summary = data.get("summary") or {}
    exposure = summary.get("exposure") or {}
    blocks: List[Block] = []

    risk = []
    if exposure.get("volatility") is not None:
        risk.append(f"Volatility {exposure['volatility']:.1%}/yr")
    betas = [b for b in exposure.get("betas") or [] if b.get("beta") is not None]
    if betas:
        risk.append("Beta " + ", ".join(f"{b['beta']:.2f} vs {b['benchmark']}" for b in betas))
    if exposure.get("effective_positions") is not None:
        line = f"Effective positions {exposure['effective_positions']:.0f}"
        if exposure.get("effective_risk_positions") is not None:
            line += f" (by risk {exposure['effective_risk_positions']:.0f})"
        risk.append(line)
    if risk:
        blocks.append("   ".join(risk))

    facts = []
    if exposure.get("top5") is not None:
        facts.append(f"Top 5 {exposure['top5']:.0%}, top 10 {exposure['top10']:.0%}")
    largest = summary.get("largest") or {}
    if largest.get("weight") is not None:
        facts.append(f"Largest {largest['ticker']} {largest['weight']:.1%}")
    if summary.get("diversification_score") is not None:
        facts.append(
            f"Diversification {summary['diversification_score']}/100 "
            f"(average correlation {summary.get('average_correlation', 0):.2f})"
        )
    if facts:
        blocks.append("   ".join(facts))

    for flag in summary.get("concentration_flags") or []:
        blocks.append(f"!  {flag}")

    groups = [
        (label, exposure.get(key) or [])
        for label, key in (
            ("By sector", "by_sector"),
            ("By country", "by_country"),
            ("By currency", "by_currency"),
        )
    ]
    if any(rows for _, rows in groups):
        blocks += ["", "Share of value / share of risk:"]
        blocks += [f"  {label}: {_groups(rows)}" for label, rows in groups if rows]

    factors = exposure.get("factors") or []
    if factors:
        blocks += ["", "Factor tilts (stocks only, weighted median):"]
        blocks.append(
            Table(
                ["Factor", "Measure", "Median", "Lowest", "Highest", "Coverage"],
                [
                    [
                        f["factor"],
                        _MEASURES.get(f["measure"], f["measure"]),
                        _factor_value(f["measure"], f.get("median")),
                        f"{f['low']['ticker']} {_factor_value(f['measure'], f['low']['value'])}",
                        f"{f['high']['ticker']} {_factor_value(f['measure'], f['high']['value'])}",
                        f"{f['coverage']:.0%}" if f.get("coverage") is not None else "",
                    ]
                    for f in factors
                ],
                "llrllr",
            )
        )
    dims = {k: v for k, v in (exposure.get("dimensions") or {}).items() if v is not None}
    if dims:
        blocks.append(
            "Vet dimensions (weighted, 50 = neutral): "
            + ", ".join(f"{name} {score:.0f}" for name, score in dims.items())
        )

    pairs = summary.get("correlated_pairs") or []
    if pairs:
        blocks += ["", f"Move together (weekly-return correlation >= 0.80), {len(pairs)} pair(s):"]
        blocks += [
            f"  {p['pair'][0]} / {p['pair'][1]}  {p['correlation']:.2f}" for p in pairs[:TOP_PAIRS]
        ]
        if len(pairs) > TOP_PAIRS:
            blocks.append(f"  ... and {len(pairs) - TOP_PAIRS} more (see --json)")

    if exposure.get("weeks"):
        note = (
            f"Risk numbers: {exposure['weeks']} weeks of {data.get('base_currency')} returns "
            f"to {exposure.get('end')}, covering {exposure.get('coverage', 0):.0%} of the value"
        )
        if exposure.get("shrinkage") is not None:
            note += f"; covariance shrinkage {exposure['shrinkage']:.2f}"
        blocks += ["", note]
    if exposure.get("excluded"):
        blocks.append("Too little history for the risk numbers: " + ", ".join(exposure["excluded"]))
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
    blocks: List[Block] = [_targets_note((data.get("summary") or {}).get("targets") or {})]
    blocks += CAVEATS
    unmapped = data.get("unmapped") or []
    if unmapped:
        blocks.append(
            f"No ticker for {len(unmapped)} name(s), left out: {', '.join(unmapped)}. "
            "Add them to portfolio/tickers.csv and rerun import-portfolio."
        )
    return Section("NOTES", blocks)


def _targets_note(notes: Dict[str, Any]) -> str:
    """How the Target column was set, in one line."""
    if not notes:
        return "No targets (no price history)."
    limits = notes.get("limits") or {}
    text = (
        "Targets: equal risk contribution (each holding the same share of risk), "
        f"positions up to {limits.get('max_position', 0):.0%}, "
        f"sectors up to {limits.get('max_sector', 0):.0%}"
        + (f" (from {notes['source']})" if notes.get("source") else " (defaults)")
        + ". Exits get 0; Review holdings and short histories keep their weight"
    )
    if notes.get("fixed"):
        text += "; fixed: " + ", ".join(notes["fixed"])
    if notes.get("capped"):
        text += "; capped: " + ", ".join(notes["capped"])
    if notes.get("unallocated", 0) > 0.0005:
        text += f"; {notes['unallocated']:.1%} unallocated (every holding at its cap)"
    return text + "."


# ==================== Formatting ====================


_MEASURES = {
    "earnings_yield": "earnings yield",
    "roe": "ROE",
    "momentum": "12-1 month return",
    "volatility": "volatility",
}


def _groups(rows: List[Dict[str, Any]], limit: int = 6) -> str:
    """'Energy 20%/31%, ...': value weight / risk share (risk left out when unknown)."""
    parts = []
    for r in rows[:limit]:
        risk = f"/{r['risk']:.0%}" if r.get("risk") is not None else ""
        parts.append(f"{r['name']} {r['weight']:.0%}{risk}")
    return ", ".join(parts) + (", ..." if len(rows) > limit else "")


def _factor_value(measure: str, value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value):+.1%}" if measure == "momentum" else f"{float(value):.1%}"


def _share(value: Any) -> str:
    return f"{float(value):.1%}" if value is not None else ""


def _pct(value: Any, decimals: int = 1) -> str:
    return f"{float(value):+.{decimals}f}%" if value is not None else ""


def _money(value: Any, ccy: str) -> str:
    return f"{float(value):,.0f} {ccy}" if value is not None else "N/A"


def _short(text: str) -> str:
    return text if len(text) <= REASON_WIDTH else text[: REASON_WIDTH - 3] + "..."


# ==================== Rebalance proposal ====================

REBALANCE_CAVEATS = [
    "Rule-based suggestions from free Yahoo data, not advice.",
    "No trading costs or spreads; prices are the latest close.",
    "Risk numbers use two years of weekly returns in the base currency.",
    "AF tax is 37.84% of the gain, and a loss deducts at the same rate (net against gains "
    "in the same year); the cost is at today's FX rate, with no shielding deduction "
    "(skjermingsfradrag).",
    "ASK eligibility is judged from Yahoo's headquarters country, which isn't always the domicile.",
]
MIN_MIX_CHANGE = 0.005  # mix lines show groups that moved at least half a point


def build_proposal_sections(data: Dict[str, Any]) -> List[Section]:
    return [_trades_section(data), _before_after_section(data), _proposal_notes(data)]


def render_proposal_text(data: Dict[str, Any]) -> str:
    return sections_to_text(build_proposal_sections(data))


def render_proposal_markdown(data: Dict[str, Any]) -> str:
    return sections_to_markdown(build_proposal_sections(data))


def _trades_section(data: Dict[str, Any]) -> Section:
    ccy = data.get("base_currency") or ""
    trades = data.get("trades") or []
    blocks: List[Block] = [proposal_headline(data), ""]
    if not trades:
        blocks.append("No trades: every holding is within its target and limits.")
        return Section("REBALANCE PROPOSAL", blocks)
    rows = [
        [
            t["side"].upper(),
            t["ticker"] + (" (new)" if t.get("new") else ""),
            f"{t['shares']:,.0f}" if float(t["shares"]).is_integer() else f"{t['shares']:,.4f}",
            f"{t['amount']:,.0f}",
            t.get("account") or "",
            f"{t['tax']:+,.0f}" if t.get("tax") else "",
            _short(t.get("reason") or ""),
        ]
        for t in trades
    ]
    blocks.append(
        Table(
            ["Side", "Ticker", "Shares", f"Amount ({ccy})", "Account", "Est. tax", "Reason"],
            rows,
            "llrrlrl",
        )
    )
    return Section("REBALANCE PROPOSAL", blocks)


def proposal_headline(data: Dict[str, Any]) -> str:
    """'4 sells (82,000 NOK), 3 buys (75,000 NOK), cash left 7,000 NOK; volatility ...'"""
    ccy = data.get("base_currency") or ""
    trades = data.get("trades") or []
    sells = {t["ticker"] for t in trades if t["side"] == "Sell"}
    buys = {t["ticker"] for t in trades if t["side"] == "Buy"}
    parts = [
        f"{len(sells)} sell(s) ({_money(data.get('proceeds'), ccy)}), "
        f"{len(buys)} buy(s) ({_money(data.get('spent'), ccy)}), "
        f"cash left {_money(data.get('cash_left'), ccy)}"
    ]
    taxes = [t["tax"] for t in trades if t.get("tax")]
    if taxes:
        gains = sum(t for t in taxes if t > 0)
        losses = sum(t for t in taxes if t < 0)
        text = f"estimated AF tax {_money(data.get('tax'), ccy)}"
        if gains and losses:
            text += f" ({gains:+,.0f} on gains, {losses:+,.0f} from losses)"
        parts.append(text)
    before, after = data.get("before") or {}, data.get("after") or {}
    if before.get("volatility") is not None and after.get("volatility") is not None:
        parts.append(f"volatility {before['volatility']:.1%} -> {after['volatility']:.1%}")
    moves = _mix_changes(before.get("by_sector") or [], after.get("by_sector") or [])
    if moves:
        name, old, new = moves[0]
        parts.append(f"{name} {old:.0%} -> {new:.0%}")
    return "; ".join(parts)


def _before_after_section(data: Dict[str, Any]) -> Section:
    before, after = data.get("before") or {}, data.get("after") or {}
    if not before or not after:
        return Section("BEFORE / AFTER", ["No risk numbers (no price history)"])

    def beta(summary: Dict[str, Any], label: str) -> Any:
        return next(
            (b["beta"] for b in summary.get("betas") or [] if b["benchmark"] == label), None
        )

    rows = [
        ["Volatility", _share(before.get("volatility")), _share(after.get("volatility"))],
        *(
            [f"Beta vs {b['benchmark']}", _num(b.get("beta")), _num(beta(after, b["benchmark"]))]
            for b in before.get("betas") or []
        ),
        [
            "Effective positions",
            _num(before.get("effective_positions"), 0),
            _num(after.get("effective_positions"), 0),
        ],
        [
            "Effective positions by risk",
            _num(before.get("effective_risk_positions"), 0),
            _num(after.get("effective_risk_positions"), 0),
        ],
        ["Top 5 weight", _share(before.get("top5")), _share(after.get("top5"))],
    ]
    blocks: List[Block] = [Table(["", "Before", "After"], rows, "lrr")]
    for label, key in (
        ("By sector", "by_sector"),
        ("By country", "by_country"),
        ("By currency", "by_currency"),
    ):
        moves = _mix_changes(before.get(key) or [], after.get(key) or [])
        if moves:
            text = ", ".join(f"{n} {old:.0%} -> {new:.0%}" for n, old, new in moves[:6])
            blocks.append(f"{label}: {text}")
    return Section("BEFORE / AFTER", blocks)


def _proposal_notes(data: Dict[str, Any]) -> Section:
    blocks: List[Block] = [f"Not traded: {note}" for note in data.get("notes") or []]
    if data.get("reserve"):
        blocks.append(
            f"Cash reserve kept: {_money(data['reserve'], data.get('base_currency') or '')}"
        )
    return Section("NOTES", [*blocks, *REBALANCE_CAVEATS])


def _mix_changes(
    before: List[Dict[str, Any]], after: List[Dict[str, Any]]
) -> List[tuple[str, float, float]]:
    """Groups whose value share moved, largest move first: (name, before, after)."""
    old = {g["name"]: g["weight"] or 0.0 for g in before}
    new = {g["name"]: g["weight"] or 0.0 for g in after}
    moves = [(n, old.get(n, 0.0), new.get(n, 0.0)) for n in {*old, *new}]
    moves = [m for m in moves if abs(m[2] - m[1]) >= MIN_MIX_CHANGE]
    return sorted(moves, key=lambda m: abs(m[2] - m[1]), reverse=True)


def _num(value: Any, decimals: int = 2) -> str:
    return f"{float(value):.{decimals}f}" if value is not None else ""
