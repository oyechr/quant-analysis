"""
Markdown rendering of the consolidated report (report.md)

One builder per section. Each takes its part of the report dict and returns
its lines, or no lines when it has nothing to show. Text from Yahoo (firm,
holder and headline names) goes through `_md_cell` / `_md_link`, so a `|` or
a `]` can't break a table or a link.
"""

import numbers
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..analysis.fundamental import altman_zones
from ..markets import benchmark_name
from ..scoring.scorer import ScoringResult
from ..utils.report import (
    CALMAR_LADDER,
    SHARPE_LADDER,
    SORTINO_LADDER,
    format_number,
    get_currency_symbol,
    rate_ratio,
)

Lines = List[str]
Ladder = Sequence[Tuple[float, str]]

# Plain-language notes. `_above` takes the first label whose threshold the
# value exceeds; `_below` the first whose threshold it is under.
DIMENSION_NOTES: Ladder = ((70, "Strong"), (50, "Adequate"), (30, "Weak"))  # inclusive
PE_NOTES: Ladder = ((15, "cheap relative to earnings"), (25, "fairly priced"), (50, "expensive"))
PEG_NOTES: Ladder = ((1, "undervalued relative to growth"), (2, "fairly valued"))
ROE_NOTES: Ladder = ((20, "excellent"), (10, "good"), (0, "fair"))  # percent
DEBT_EQUITY_NOTES: Ladder = ((0.5, "conservative"), (1.5, "moderate"), (3, "elevated"))  # ratio
CURRENT_RATIO_NOTES: Ladder = ((2, "strong short-term liquidity"), (1, "adequate"))
BETA_NOTES: Ladder = (
    (2, "very aggressive, large swings"),
    (1.2, "above-average sensitivity"),
    (0.8, "moves roughly with the market"),
)
ADX_NOTES: Ladder = ((20, "no clear trend"), (25, "trend developing"), (40, "strong trend"))
VOLUME_NOTES: Ladder = (
    (1.5, "well above average (high interest)"),
    (1.1, "above average"),
    (0.7, "near average"),
)
GROSS_MARGIN_NOTES: Ladder = ((60, "strong pricing power"), (40, "healthy"), (20, "thin"))
OPERATING_MARGIN_NOTES: Ladder = ((25, "excellent operations"), (10, "healthy"), (0, "tight"))
NET_MARGIN_NOTES: Ladder = ((20, "highly profitable"), (10, "solid"), (0, "modest"))
PIOTROSKI_NOTES: Ladder = ((8, "Strong fundamentals"), (5, "Average"))  # inclusive
BENEISH_NOTES: Ladder = ((-2.22, "Low manipulation risk"), (-1.78, "Inconclusive (grey zone)"))
CASH_CONVERSION_NOTES: Ladder = (  # inclusive, percent
    (100, "excellent cash generation"),
    (80, "healthy"),
    (60, "some cash leakage"),
)
VOLATILITY_NOTES: Ladder = (
    (0.5, "very high (>50%)"),
    (0.3, "elevated (30-50%)"),
    (0.15, "moderate (15-30%)"),
)

RATING_KEYS = ("strongBuy", "buy", "hold", "sell", "strongSell")
GRADE_ACTIONS = {
    "up": "Upgrade",
    "down": "Downgrade",
    "main": "Maintains",
    "reit": "Reiterates",
    "init": "Initiates",
}
MAX_ROWS = 5


def render_report_markdown(
    ticker: str, data: Dict[str, Any], scoring_result: Optional[ScoringResult] = None
) -> str:
    """
    report.md as a comprehensive, consolidated analysis document.

    Combines scoring, technicals, fundamentals, risk, and valuation into
    a single complete report. Written for an intelligent reader who may not
    be a finance professional — includes plain-language annotations alongside
    the numbers. No emojis.
    """
    info = data.get("info") or {}
    currency = info.get("currency") or "USD"
    sym = get_currency_symbol(currency)
    price = _current_price(data)

    md = _header(ticker, data, info)
    md += _score_section(scoring_result)
    md += _overview_section(info, data.get("price_data") or {}, currency, price)
    md += _technical_section(data.get("technical_analysis") or {}, sym)
    md += _fundamental_section(data.get("fundamental_analysis") or {})
    md += _risk_section(data.get("risk_analysis") or {})
    md += _valuation_section(data.get("valuation_analysis") or {}, sym, price)
    md += _analyst_section(data.get("analyst_ratings") or {}, sym)
    md += _holders_section(data.get("holders") or {})
    md += _news_section(data.get("news") or {})
    return "\n".join(md)


# ==================== Sections ====================


def _header(ticker: str, data: Dict[str, Any], info: Dict[str, Any]) -> Lines:
    md = [
        f"# {ticker} — Full Analysis Report",
        "",
        f"**{info.get('name', ticker)}** | {info.get('sector', 'N/A')} | {info.get('industry', 'N/A')}",
        f"**Generated:** {data['generated_at'][:10]} | **Period:** {data.get('period', '1y')}",
    ]
    if info.get("website") and info.get("website") != "N/A":
        md.append(f"**Website:** {info['website']}")
    md.append("")
    return md


def _score_section(result: Optional[ScoringResult]) -> Lines:
    if not result:
        return []
    md = _rule(f"Composite Score: {result.composite_score:.0f}/100 — {result.signal}")
    md += [f"**Confidence:** {result.confidence} ({result.confidence_score:.0%})", ""]

    rows = []
    for dim in (result.technical, result.fundamental, result.risk, result.valuation):
        if dim:
            filled = int(dim.score / 5)
            bar = "#" * filled + "-" * (20 - filled)
            assessment = _above(dim.score, DIMENSION_NOTES, "Very Weak", inclusive=True)
            rows.append(
                [
                    dim.dimension,
                    f"{dim.score:.1f}/100 [{bar}]",
                    f"{dim.data_coverage:.0%}",
                    assessment,
                ]
            )
    md += _table(["Dimension", "Score", "Coverage", "Assessment"], rows)

    for title, items in (("Key Strengths", result.strengths), ("Key Concerns", result.concerns)):
        if items:
            md += [f"**{title}:**", ""] + [f"- {item}" for item in items] + [""]

    if result.trade_levels:
        md.extend(result.trade_levels.format_markdown())
    return md


def _overview_section(
    info: Dict[str, Any], price_data: Dict[str, Any], currency: str, price: Optional[float]
) -> Lines:
    sym = get_currency_symbol(currency)
    md = _rule("Company Overview")

    if price:
        md.append(f"**Current Price:** {sym}{price:.2f}")
    stats = price_data.get("statistics") or {}
    high, low = stats.get("high_52w"), stats.get("low_52w")
    if high and low:
        range_text = f"**52-Week Range:** {sym}{low:.2f} – {sym}{high:.2f}"
        if price:
            range_pct = (price - low) / (high - low) * 100 if high != low else 50
            range_text += f" (at {range_pct:.0f}% of range)"
        md.append(range_text)
    md += [f"**Market Cap:** {format_number(info.get('market_cap'), currency)}", ""]

    rows = []
    pe = info.get("pe_ratio")
    if pe and pe > 0:
        rows.append(
            ["P/E Ratio", f"{pe:.1f}", f"Considered {_below(pe, PE_NOTES, 'very expensive')}"]
        )
    else:
        rows.append(["P/E Ratio", "N/A", "Company is not currently profitable"])

    fwd_pe = info.get("forward_pe")
    if fwd_pe and fwd_pe > 0:
        rows.append(["Forward P/E", f"{fwd_pe:.1f}", "Based on analyst earnings forecasts"])

    peg = info.get("peg_ratio")
    if peg and peg > 0:
        rows.append(["PEG Ratio", f"{peg:.2f}", _below(peg, PEG_NOTES, "growth priced in").title()])

    roe = info.get("roe")
    if roe:
        roe_pct = roe * 100
        note = _above(roe_pct, ROE_NOTES, "negative — losing money")
        rows.append(["Return on Equity", f"{roe_pct:.1f}%", note.title()])

    # Yahoo gives debt/equity in percent (150 = 1.5x)
    de_pct = info.get("debt_to_equity")
    if de_pct is not None:
        de = de_pct / 100
        note = _below(de, DEBT_EQUITY_NOTES, "very high")
        rows.append(["Debt/Equity", f"{de:.2f}x", f"Leverage is {note}"])

    cr = info.get("current_ratio")
    if cr:
        note = _above(cr, CURRENT_RATIO_NOTES, "potential liquidity concern")
        rows.append(["Current Ratio", f"{cr:.2f}", note.title()])

    # Yahoo gives the dividend yield in percent (0.31 = 0.31%)
    div_yield = info.get("dividend_yield")
    if div_yield and div_yield > 0:
        rows.append(
            ["Dividend Yield", f"{div_yield:.2f}%", "Annual dividends as a share of the price"]
        )

    beta = info.get("beta")
    if beta:
        note = _above(beta, BETA_NOTES, "defensive, lower sensitivity")
        rows.append(["Beta", f"{beta:.2f}", note.title()])

    return md + _table(["Metric", "Value", "Meaning"], rows)


def _technical_section(tech: Dict[str, Any], sym: str) -> Lines:
    if not tech:
        return []
    md = _rule("Technical Analysis")
    signals = tech.get("signals") or {}
    latest = tech.get("latest_values") or {}
    stats = tech.get("statistics") or {}

    if signals:
        md += [
            "> Technical indicators assess price trends, momentum, and trading patterns.",
            "> They do not predict future prices but identify the current market posture.",
            "",
            "### Signal Summary",
            "",
        ]
        md += _table(["Indicator", "Reading"], [[k, v] for k, v in signals.items()])

    if latest:
        sma50, sma200 = latest.get("SMA_50"), latest.get("SMA_200")
        rows = [
            [label, f"{sym}{value:.2f}", meaning]
            for label, value, meaning in (
                ("50-Day Moving Average", sma50, "Short-term trend reference"),
                ("200-Day Moving Average", sma200, "Long-term trend reference"),
                ("Bollinger Upper Band", latest.get("BB_UPPER"), "Overbought zone"),
                ("Bollinger Lower Band", latest.get("BB_LOWER"), "Oversold zone"),
            )
            if value
        ]
        md += ["### Key Levels", ""]
        md += _table(["Level", "Price", "Significance"], rows)
        if sma50 and sma200:
            if sma50 > sma200:
                md += ["**Trend:** 50-day MA is ABOVE 200-day MA (an uptrend)", ""]
            else:
                md += ["**Trend:** 50-day MA is BELOW 200-day MA (a downtrend)", ""]

        md += ["### Momentum & Trend Strength", ""]
        rsi = latest.get("RSI")
        if rsi is not None:
            if rsi < 30:
                rsi_note = "oversold — potential bounce"
            elif rsi > 70:
                rsi_note = "overbought — potential pullback"
            else:
                rsi_note = "neutral territory"
            md.append(f"- **RSI (14):** {rsi:.1f} — {rsi_note}")
        adx = latest.get("ADX")
        if adx is not None:
            md.append(f"- **ADX (14):** {adx:.1f} — {_below(adx, ADX_NOTES, 'very strong trend')}")
        macd, macd_sig = latest.get("MACD_12_26"), latest.get("MACD_Signal")
        if macd is not None and macd_sig is not None:
            macd_dir = "above signal (bullish)" if macd > macd_sig else "below signal (bearish)"
            md.append(f"- **MACD:** {macd:.4f}, Signal: {macd_sig:.4f} — {macd_dir}")
        md.append("")

    avg_vol, latest_vol = stats.get("avg_volume"), stats.get("current_volume")
    if avg_vol and latest_vol:
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1
        vol_note = _above(vol_ratio, VOLUME_NOTES, "below average (low interest)")
        md += [f"**Volume:** {latest_vol:,.0f} ({vol_note}, avg: {avg_vol:,.0f})", ""]
    return md


def _fundamental_section(fund: Dict[str, Any]) -> Lines:
    if not fund:
        return []
    md = _rule("Fundamental Analysis")
    md += [
        "> Fundamentals measure the financial health and operational performance of the business itself,",
        "> independent of its stock price movement.",
        "",
    ]
    analysis = fund.get("analysis", fund)
    md += _growth_lines(analysis.get("growth_rates") or {})
    md += _margin_lines((analysis.get("margins") or {}).get("current") or {})
    md += _quality_lines(analysis.get("quality_scores") or {})

    dupont = analysis.get("dupont") or {}
    if dupont.get("roe_calculated"):
        md += [
            "### ROE Decomposition (DuPont)",
            "",
            "> Breaks Return on Equity into its three drivers to see WHERE profitability comes from.",
            "",
            f"- Net Margin: {dupont.get('net_margin', 0):.1f}% (how much revenue becomes profit)",
            f"- Asset Turnover: {dupont.get('asset_turnover', 0):.2f}x (how efficiently assets generate revenue)",
            f"- Equity Multiplier: {dupont.get('equity_multiplier', 0):.2f}x (how much leverage is used)",
            f"- **Resulting ROE: {dupont['roe_calculated']:.1f}%**",
            "",
        ]
    return md


def _growth_lines(growth: Dict[str, Any]) -> Lines:
    rows = []
    for label, key in (("Revenue", "revenue"), ("Earnings", "earnings"), ("Free Cash Flow", "fcf")):
        rate = growth.get(key)
        if rate:
            rows.append([label, _signed_pct(rate.get("1y")), _signed_pct(rate.get("3y_cagr"))])
    if not rows:
        return []
    return ["### Growth", ""] + _table(["Metric", "1 Year", "3 Year (CAGR)"], rows)


def _margin_lines(margins: Dict[str, Any]) -> Lines:
    if not margins:
        return []
    rows = []
    for label, key, ladder, lowest in (
        ("Gross Margin", "gross_margin", GROSS_MARGIN_NOTES, "very thin"),
        ("Operating Margin", "operating_margin", OPERATING_MARGIN_NOTES, "operating at a loss"),
        ("Net Margin", "net_margin", NET_MARGIN_NOTES, "unprofitable"),
    ):
        value = margins.get(key)
        if value is not None:
            rows.append([label, f"{value:.1f}%", _above(value, ladder, lowest).title()])
    return ["### Profitability", ""] + _table(["Margin", "Value", "Meaning"], rows)


def _quality_lines(quality: Dict[str, Any]) -> Lines:
    if not quality:
        return []
    md = [
        "### Financial Quality & Integrity",
        "",
        "> These scores detect problems that standard metrics miss — bankruptcy risk,",
        "> earnings manipulation, and whether reported profits are backed by real cash.",
        "",
    ]
    z = quality.get("altman_z")
    if z:
        model = quality.get("altman_model") or "Z"
        distress, safe = altman_zones(model)
        if z > safe:
            z_note = "Safe zone — low bankruptcy risk"
        elif z > distress:
            z_note = "Grey zone — some financial stress"
        else:
            z_note = "DISTRESS zone — elevated bankruptcy risk"
        md.append(f"- **Altman {model}-Score: {z:.2f}** — {z_note}")

    f_score = quality.get("piotroski_f")
    if f_score is not None:
        f_note = _above(f_score, PIOTROSKI_NOTES, "Weak fundamentals", inclusive=True)
        md.append(f"- **Piotroski F-Score: {f_score}/9** — {f_note}")

    beneish = quality.get("beneish_m")
    if isinstance(beneish, dict) and beneish.get("m_score") is not None:
        m = beneish["m_score"]
        m_note = _below(m, BENEISH_NOTES, "HIGH manipulation risk — earnings may be inflated")
        md.append(f"- **Beneish M-Score: {m:.2f}** — {m_note}")

    accruals = quality.get("accruals_quality")
    if isinstance(accruals, dict) and accruals.get("accrual_ratio_pct") is not None:
        ratio = accruals["accrual_ratio_pct"]
        md.append(f"- **Accruals Ratio: {ratio:.1f}%** — {accruals.get('interpretation', '')}")

    cash_conv = quality.get("cash_conversion")
    if isinstance(cash_conv, dict) and cash_conv.get("conversion_ratio_pct") is not None:
        conv = cash_conv["conversion_ratio_pct"]
        conv_note = _above(
            conv,
            CASH_CONVERSION_NOTES,
            "poor — significant gap between earnings and cash",
            inclusive=True,
        )
        md.append(f"- **Cash Conversion: {conv:.0f}%** — {conv_note.title()}")
        if cash_conv.get("persistent_poor_conversion"):
            md.append("  - WARNING: Persistently poor conversion over multiple years")
    md.append("")
    return md


def _risk_section(risk: Dict[str, Any]) -> Lines:
    if not risk:
        return []
    md = _rule("Risk Analysis")

    regime = risk.get("regime") or {}
    if regime:
        md += [
            f"**Current Market Regime: {regime.get('regime', 'unknown').upper()}**",
            f"*{regime.get('description', '')}*",
            "",
        ]

    returns = risk.get("returns") or {}
    vol = risk.get("volatility") or {}
    if returns or vol:
        rows = []
        if returns.get("annualized_return") is not None:
            rows.append(
                [
                    "Annualized Return",
                    f"{returns['annualized_return']:.1%}",
                    "Total return extrapolated to one year",
                ]
            )
        if returns.get("win_rate") is not None:
            rows.append(
                ["Win Rate", f"{returns['win_rate']:.0%}", "Percentage of positive trading days"]
            )
        if vol.get("annualized_volatility") is not None:
            av = vol["annualized_volatility"]
            note = _above(av, VOLATILITY_NOTES, "low (<15%)")
            rows.append(["Annualized Volatility", f"{av:.1%}", note.title()])
        if vol.get("downside_deviation") is not None:
            rows.append(
                [
                    "Downside Deviation",
                    f"{vol['downside_deviation']:.1%}",
                    "Volatility of losses only",
                ]
            )
        md += ["### Performance & Volatility", ""]
        md += _table(["Metric", "Value", "Context"], rows)

    md += [
        "### Risk-Adjusted Performance",
        "",
        "> These ratios measure return PER UNIT OF RISK. Higher is always better.",
        "",
    ]
    rows = []
    for name, value, ladder, lowest, meaning in (
        (
            "Sharpe",
            risk.get("sharpe_ratio"),
            SHARPE_LADDER,
            "Negative",
            "Return per unit of total risk",
        ),
        (
            "Sortino",
            risk.get("sortino_ratio"),
            SORTINO_LADDER,
            "Poor",
            "Return per unit of downside risk",
        ),
        (
            "Calmar",
            risk.get("calmar_ratio"),
            (*CALMAR_LADDER, (0.0, "Weak")),
            "Negative",
            "Return divided by worst drawdown",
        ),
    ):
        text, rating = rate_ratio(value, ladder, lowest)
        rows.append([name, text, rating, meaning])
    md += _table(["Ratio", "Value", "Rating", "What it measures"], rows)

    md += _drawdown_lines(risk.get("drawdown") or {})
    md += _market_lines(risk.get("market_risk") or {})
    md += _tail_lines(risk.get("var_95") or {}, risk.get("var_99") or {})
    md += _distribution_lines(risk.get("distribution") or {})
    md += _kelly_lines(risk.get("kelly_criterion") or {})
    return md


def _drawdown_lines(dd: Dict[str, Any]) -> Lines:
    if not dd:
        return []
    md = ["### Drawdown", "", f"- **Maximum drawdown:** {dd.get('max_drawdown', 0):.1%}"]
    if dd.get("max_drawdown_date"):
        md.append(f"  - Occurred: {dd['max_drawdown_date']}")
    current = dd.get("current_drawdown", 0)
    if dd.get("is_recovered"):
        md.append("- **Status:** Recovered to prior peak")
    elif current == current:  # NaN check
        md.append(
            f"- **Current drawdown:** {current:.1%} ({dd.get('days_since_peak', 0)} days below peak)"
        )
    if dd.get("recovery_days"):
        md.append(f"- **Previous recovery:** took {dd['recovery_days']} days")
    md.append("")
    return md


def _market_lines(mr: Dict[str, Any]) -> Lines:
    if not mr:
        return []
    beta = mr.get("beta", 0)
    alpha = mr.get("alpha", 0)
    verdict = "outperforming" if alpha > 0 else "underperforming"
    return [
        "### Market Sensitivity",
        "",
        f"- **Beta: {beta:.2f}** — stock moves ~{beta:.1f}x the market on average",
        f"- **Alpha: {alpha:.1%}** — {verdict} what its risk level predicts",
        f"- **Correlation to {benchmark_name(mr.get('benchmark'))}:** {mr.get('correlation', 0):.0%}",
        f"- **R-squared:** {mr.get('r_squared', 0):.0%} (how much of movement is explained by market)",
        "",
    ]


def _tail_lines(var95: Dict[str, Any], var99: Dict[str, Any]) -> Lines:
    if not var95:
        return []
    md = [
        "### Tail Risk (Value at Risk)",
        "",
        f"- On a bad day (5% probability): loss of **{abs(var95.get('var_historical', 0)):.1%}** or more",
    ]
    if var99:
        md += [
            f"- On a very bad day (1% probability): loss of **{abs(var99.get('var_historical', 0)):.1%}** or more",
            f"- Worst actual day in period: **{var99.get('worst_day', 0):.1%}**",
        ]
    md.append("")
    return md


def _distribution_lines(dist: Dict[str, Any]) -> Lines:
    if not dist:
        return []
    md = [
        "### Return Distribution",
        "",
        f"- **Skewness: {dist.get('skewness', 0):.2f}** — {dist.get('skew_interpretation', 'N/A')}",
        f"- **Excess Kurtosis: {dist.get('excess_kurtosis', 0):.2f}** — {dist.get('kurtosis_interpretation', 'N/A')}",
    ]
    if not dist.get("is_normally_distributed", True):
        md.append(
            "- Returns are NOT normally distributed — standard risk models may understate true risk"
        )
        tail_ratio = dist.get("tail_risk_ratio")
        if tail_ratio and tail_ratio > 1.3:
            md.append(
                f"- Actual extreme losses are {tail_ratio:.1f}x worse than a normal model predicts"
            )
    md.append("")
    return md


def _kelly_lines(kelly: Dict[str, Any]) -> Lines:
    if not kelly:
        return []
    md = [
        "### Position Sizing (Kelly Criterion)",
        "",
        f"- Win rate: {kelly.get('win_rate', 0):.0%} of days positive",
        f"- Payoff ratio: {kelly.get('payoff_ratio', 0):.2f}x (avg win / avg loss)",
    ]
    if kelly.get("kelly_pct", 0) > 0:
        md.append(
            f"- **Recommended allocation (half-Kelly): {kelly.get('half_kelly_pct', 0):.1f}% of portfolio**"
        )
    else:
        md.append("- Kelly is negative — no statistical edge for position sizing")
    md += [f"- Assessment: {kelly.get('description', '')}", ""]
    return md


def _valuation_section(val: Dict[str, Any], sym: str, price: Optional[float]) -> Lines:
    if not val:
        return []
    md = _rule("Valuation")

    dcf = val.get("dcf_valuation") or {}
    if not dcf.get("error") and dcf.get("intrinsic_value_per_share"):
        rows = [["Intrinsic Value", f"{sym}{dcf['intrinsic_value_per_share']:,.2f}"]]
        if price:
            rows.append(["Current Price", f"{sym}{price:.2f}"])
        discount = dcf.get("discount_premium_pct", 0)
        if discount:
            direction = "undervalued" if discount < 0 else "overvalued"
            rows.append(["Assessment", f"{abs(discount):.1f}% {direction}"])
        if dcf.get("growth_rate_used"):
            rows.append(["Growth Rate", f"{dcf['growth_rate_used']:.1f}%"])
        if dcf.get("wacc_used"):
            rows.append(["Discount Rate (WACC)", f"{dcf['wacc_used']:.1f}%"])
        md += [
            "### DCF (Discounted Cash Flow)",
            "",
            "> Projects future free cash flows and discounts them back to present value.",
            "",
        ]
        md += _table(["Parameter", "Value"], rows)
    elif dcf.get("error"):
        md += [f"**DCF:** Not applicable — {dcf['error']}", ""]

    md += _monte_carlo_lines(val.get("monte_carlo_valuation") or {}, sym, price)

    ddm = val.get("ddm_valuation") or {}
    if not ddm.get("error") and ddm.get("intrinsic_value_per_share"):
        md += [
            "### Dividend Discount Model",
            "",
            f"- Intrinsic value: {sym}{ddm['intrinsic_value_per_share']:,.2f}",
        ]
        if ddm.get("growth_rate_used"):
            md.append(f"- Dividend growth assumption: {ddm['growth_rate_used']:.1f}%")
        md.append("")

    earnings = val.get("earnings_analysis") or {}
    if earnings.get("current_eps"):
        md += ["### Earnings", "", f"- Current EPS (TTM): {sym}{earnings['current_eps']:.2f}"]
        if earnings.get("forward_eps"):
            md.append(f"- Forward EPS (analyst est.): {sym}{earnings['forward_eps']:.2f}")
        if earnings.get("eps_growth_1y"):
            md.append(f"- EPS growth (1Y): {earnings['eps_growth_1y']:+.1f}%")
        if earnings.get("trend"):
            md.append(f"- Trend: {earnings['trend']}")
        md.append("")
    return md


def _monte_carlo_lines(mc: Dict[str, Any], sym: str, price: Optional[float]) -> Lines:
    if mc.get("error"):
        return [f"**Monte Carlo:** Not applicable — {mc['error']}", ""]
    if mc.get("probability_undervalued") is None:
        return []
    md = [
        "### Monte Carlo Valuation (10,000 Simulations)",
        "",
        "> Runs thousands of scenarios with varying growth, discount rates, and terminal values",
        "> to produce a probability distribution of fair values rather than a single estimate.",
        "",
        f"**Probability stock is undervalued: {mc['probability_undervalued']:.0%}**",
        "",
    ]
    scenarios = mc.get("scenarios") or {}
    if scenarios:
        rows = []
        for label, value in (
            ("Bear (10th percentile)", scenarios.get("bear_case")),
            ("Base (median)", scenarios.get("base_case")),
            ("Bull (90th percentile)", scenarios.get("bull_case")),
        ):
            if value is not None:
                diff = f"{(value - price) / price * 100:+.0f}%" if price else "—"
                rows.append([label, f"{sym}{value:,.2f}", diff])
        md += _table(["Scenario", "Fair Value", "vs. Current"], rows)
    ci = mc.get("confidence_intervals") or {}
    if ci:
        md += [
            f"50% confidence range: {sym}{ci.get('ci_25', 0):,.2f} – {sym}{ci.get('ci_75', 0):,.2f}",
            "",
        ]
    return md


def _analyst_section(ratings: Dict[str, Any], sym: str) -> Lines:
    """Yahoo's current rating counts, then the latest rating changes."""
    recs = ratings.get("recent_recommendations") or []
    latest = recs[0] if recs and isinstance(recs[0], dict) else {}
    counts = {key: _count(latest.get(key)) for key in RATING_KEYS}
    total = sum(counts.values())
    changes = [c for c in ratings.get("recent_changes") or [] if isinstance(c, dict)]
    if not total and not changes:
        return []

    md = _rule("Analyst Consensus")
    if total:
        buys = counts["strongBuy"] + counts["buy"]
        sells = counts["sell"] + counts["strongSell"]
        md += [
            f"**{buys} Buy** | {counts['hold']} Hold | {sells} Sell (from {total} analysts)",
            "",
        ]
    if changes:
        rows = []
        for change in changes[:MAX_ROWS]:
            action = change.get("Action") or ""
            grade = change.get("ToGrade") or ""
            previous = change.get("FromGrade")
            if previous and grade and previous != grade:
                grade = f"{previous} → {grade}"
            target = change.get("currentPriceTarget")
            rows.append(
                [
                    str(change.get("GradeDate") or "")[:10] or "—",
                    change.get("Firm") or "N/A",
                    GRADE_ACTIONS.get(action, action),
                    grade,
                    f"{sym}{target:,.2f}" if _positive(target) else "—",
                ]
            )
        md += ["**Recent rating changes:**", ""]
        md += _table(["Date", "Firm", "Action", "Rating", "Target"], rows)
    return md


def _holders_section(holders: Dict[str, Any]) -> Lines:
    rows = [
        [h.get("Holder") or "N/A", f"{h['pctHeld']:.2%}"]
        for h in (holders.get("top_institutional") or [])[:MAX_ROWS]
        if isinstance(h, dict) and _positive(h.get("pctHeld"))
    ]
    if not rows:
        return []
    return _rule("Top Institutional Holders") + _table(["Institution", "% Held"], rows)


def _news_section(news: Dict[str, Any]) -> Lines:
    items = [
        item
        for item in (_news_item(a) for a in news.get("recent_articles") or [])
        if item is not None
    ]
    if not items:
        return []
    md = _rule("Recent News")
    for title, url, publisher, date in items[:MAX_ROWS]:
        line = "- "
        if date:
            line += f"{date} "
        line += _md_link(title, url) if url else _md_text(title)
        if publisher:
            line += f" — *{_md_text(publisher)}*"
        md.append(line)
    md.append("")
    return md


def _news_item(article: Any) -> Optional[Tuple[str, str, str, str]]:
    """(title, url, publisher, date) from a yfinance article, or None without a title.

    yfinance nests the article under "content" (provider.displayName,
    canonicalUrl.url, pubDate); older versions gave flat title/publisher/link.
    """
    if not isinstance(article, dict):
        return None
    content = article.get("content")
    if not isinstance(content, dict):
        content = article
    title = content.get("title")
    if not title:
        return None
    provider = content.get("provider")
    publisher = provider.get("displayName") if isinstance(provider, dict) else None
    url = None
    for key in ("canonicalUrl", "clickThroughUrl"):
        link = content.get(key)
        if isinstance(link, dict) and link.get("url"):
            url = link["url"]
            break
    return (
        str(title),
        str(url or content.get("link") or ""),
        str(publisher or content.get("publisher") or ""),
        str(content.get("pubDate") or "")[:10],
    )


# ==================== Helpers ====================


def _current_price(data: Dict[str, Any]) -> Optional[float]:
    """The first positive price from info, the latest bar, or the valuation models."""
    info = data.get("info") or {}
    latest = (data.get("price_data") or {}).get("latest") or {}
    valuation = data.get("valuation_analysis") or {}
    for source in (
        info.get("currentPrice"),
        info.get("current_price"),
        latest.get("close"),
        (valuation.get("dcf_valuation") or {}).get("current_price"),
        (valuation.get("monte_carlo_valuation") or {}).get("current_price"),
    ):
        if source is not None and _positive(source):
            return float(source)
    return None


def _rule(title: str) -> Lines:
    return ["---", "", f"## {title}", ""]


def _table(headers: List[str], rows: List[List[Any]]) -> Lines:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("-" * (len(h) + 2) for h in headers) + "|",
    ]
    lines += ["| " + " | ".join(_md_cell(cell) for cell in row) + " |" for row in rows]
    return lines + [""]


def _md_text(value: Any) -> str:
    """Text on one line, with Markdown's link brackets escaped."""
    text = " ".join(str(value).split())
    return text.replace("[", "\\[").replace("]", "\\]")


def _md_cell(value: Any) -> str:
    """A table cell: one line, `|` escaped."""
    return " ".join(str(value).split()).replace("|", "\\|")


def _md_link(text: str, url: str) -> str:
    target = url.strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"[{_md_text(text)}]({target})"


def _above(value: float, ladder: Ladder, lowest: str, inclusive: bool = False) -> str:
    for threshold, label in ladder:
        if value > threshold or (inclusive and value == threshold):
            return label
    return lowest


def _below(value: float, ladder: Ladder, highest: str) -> str:
    for threshold, label in ladder:
        if value < threshold:
            return label
    return highest


def _signed_pct(value: Any) -> str:
    return f"{value:+.1f}%" if value is not None else "N/A"


def _positive(value: Any) -> bool:
    """A real positive number (False for None, NaN, text and bools)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return float(value) > 0


def _count(value: Any) -> int:
    return int(value) if _positive(value) else 0
