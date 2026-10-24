"""Markdown rendering of the consolidated report (report.md)."""

from typing import Any, Dict, Optional

from ..analysis.fundamental import altman_zones
from ..markets import benchmark_name
from ..scoring.scorer import ScoringResult
from ..utils.report import format_number, get_currency_symbol


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
    info = data.get("info", {})
    currency = info.get("currency", "USD")

    sym = get_currency_symbol(currency)

    md = []
    md.append(f"# {ticker} — Full Analysis Report")
    md.append("")
    md.append(
        f"**{info.get('name', ticker)}** | {info.get('sector', 'N/A')} | {info.get('industry', 'N/A')}"
    )
    md.append(
        f"**Generated:** {data['generated_at'][:10]} | **Period:** {data.get('period', '1y')}"
    )
    if info.get("website") and info.get("website") != "N/A":
        md.append(f"**Website:** {info['website']}")
    md.append("")

    # ===== COMPOSITE SCORE =====
    if scoring_result:
        md.append("---")
        md.append("")
        md.append(
            f"## Composite Score: {scoring_result.composite_score:.0f}/100 — {scoring_result.signal}"
        )
        md.append("")
        md.append(
            f"**Confidence:** {scoring_result.confidence} ({scoring_result.confidence_score:.0%})"
        )
        md.append("")

        md.append("| Dimension | Score | Coverage | Assessment |")
        md.append("|-----------|-------|----------|------------|")
        for dim in [
            scoring_result.technical,
            scoring_result.fundamental,
            scoring_result.risk,
            scoring_result.valuation,
        ]:
            if dim:
                bar = "#" * int(dim.score / 5) + "-" * (20 - int(dim.score / 5))
                assessment = (
                    "Strong"
                    if dim.score >= 70
                    else "Adequate"
                    if dim.score >= 50
                    else "Weak"
                    if dim.score >= 30
                    else "Very Weak"
                )
                md.append(
                    f"| {dim.dimension} | {dim.score:.1f}/100 [{bar}] | {dim.data_coverage:.0%} | {assessment} |"
                )
        md.append("")

        if scoring_result.strengths:
            md.append("**Key Strengths:**")
            md.append("")
            for s in scoring_result.strengths:
                md.append(f"- {s}")
            md.append("")

        if scoring_result.concerns:
            md.append("**Key Concerns:**")
            md.append("")
            for c in scoring_result.concerns:
                md.append(f"- {c}")
            md.append("")

        if scoring_result.trade_levels:
            md.extend(scoring_result.trade_levels.format_markdown())

    # ===== COMPANY OVERVIEW =====
    md.append("---")
    md.append("")
    md.append("## Company Overview")
    md.append("")

    # Current price from best available source
    price_data_section = data.get("price_data", {})
    latest = price_data_section.get("latest", {})
    stats = price_data_section.get("statistics", {})
    current_price = None
    for source in [
        info.get("currentPrice"),
        info.get("current_price"),
        latest.get("close"),
        (data.get("valuation_analysis") or {}).get("dcf_valuation", {}).get("current_price"),
        (data.get("valuation_analysis") or {})
        .get("monte_carlo_valuation", {})
        .get("current_price"),
    ]:
        if source and source == source and source > 0:
            current_price = source
            break

    if current_price:
        md.append(f"**Current Price:** {sym}{current_price:.2f}")
    if stats.get("high_52w") and stats.get("low_52w"):
        high = stats["high_52w"]
        low = stats["low_52w"]
        if current_price:
            range_pct = ((current_price - low) / (high - low) * 100) if high != low else 50
            md.append(
                f"**52-Week Range:** {sym}{low:.2f} – {sym}{high:.2f} (at {range_pct:.0f}% of range)"
            )
        else:
            md.append(f"**52-Week Range:** {sym}{low:.2f} – {sym}{high:.2f}")
    md.append(f"**Market Cap:** {format_number(info.get('market_cap'))}")
    md.append("")

    # Key metrics table
    md.append("| Metric | Value | Meaning |")
    md.append("|--------|-------|---------|")

    pe = info.get("pe_ratio")
    if pe and pe > 0:
        pe_note = (
            "cheap relative to earnings"
            if pe < 15
            else "fairly priced"
            if pe < 25
            else "expensive"
            if pe < 50
            else "very expensive"
        )
        md.append(f"| P/E Ratio | {pe:.1f} | Considered {pe_note} |")
    else:
        md.append("| P/E Ratio | N/A | Company is not currently profitable |")

    fwd_pe = info.get("forward_pe")
    if fwd_pe and fwd_pe > 0:
        md.append(f"| Forward P/E | {fwd_pe:.1f} | Based on analyst earnings forecasts |")

    peg = info.get("peg_ratio")
    if peg and peg > 0:
        peg_note = (
            "undervalued relative to growth"
            if peg < 1
            else "fairly valued"
            if peg < 2
            else "growth priced in"
        )
        md.append(f"| PEG Ratio | {peg:.2f} | {peg_note.title()} |")

    roe = info.get("roe")
    if roe:
        roe_pct = roe * 100
        roe_note = (
            "excellent"
            if roe_pct > 20
            else "good"
            if roe_pct > 10
            else "fair"
            if roe_pct > 0
            else "negative — losing money"
        )
        md.append(f"| Return on Equity | {roe_pct:.1f}% | {roe_note.title()} |")

    de = info.get("debt_to_equity")
    if de is not None:
        de_note = (
            "conservative"
            if de < 0.5
            else "moderate"
            if de < 1.5
            else "elevated"
            if de < 3
            else "very high"
        )
        md.append(f"| Debt/Equity | {de:.2f} | Leverage is {de_note} |")

    cr = info.get("current_ratio")
    if cr:
        cr_note = (
            "strong short-term liquidity"
            if cr > 2
            else "adequate"
            if cr > 1
            else "potential liquidity concern"
        )
        md.append(f"| Current Ratio | {cr:.2f} | {cr_note.title()} |")

    div_yield = info.get("dividend_yield")
    if div_yield and div_yield > 0:
        md.append(f"| Dividend Yield | {div_yield * 100:.2f}% | Annual income per $100 invested |")

    beta = info.get("beta")
    if beta:
        beta_note = (
            "very aggressive, large swings"
            if beta > 2
            else "above-average sensitivity"
            if beta > 1.2
            else "moves roughly with the market"
            if beta > 0.8
            else "defensive, lower sensitivity"
        )
        md.append(f"| Beta | {beta:.2f} | {beta_note.title()} |")

    md.append("")

    # ===== TECHNICAL ANALYSIS =====
    tech_data = data.get("technical_analysis", {})
    if tech_data:
        md.append("---")
        md.append("")
        md.append("## Technical Analysis")
        md.append("")

        signals = tech_data.get("signals", {})
        latest_vals = tech_data.get("latest_values", {})
        tech_stats = tech_data.get("statistics", {})

        if signals:
            md.append("> Technical indicators assess price trends, momentum, and trading patterns.")
            md.append(
                "> They do not predict future prices but identify the current market posture."
            )
            md.append("")
            md.append("### Signal Summary")
            md.append("")
            md.append("| Indicator | Reading |")
            md.append("|-----------|---------|")
            for indicator, reading in signals.items():
                md.append(f"| {indicator} | {reading} |")
            md.append("")

        # Key levels
        if latest_vals:
            md.append("### Key Levels")
            md.append("")
            md.append("| Level | Price | Significance |")
            md.append("|-------|-------|--------------|")
            sma50 = latest_vals.get("SMA_50")
            sma200 = latest_vals.get("SMA_200")
            bb_upper = latest_vals.get("BB_UPPER")
            bb_lower = latest_vals.get("BB_LOWER")

            if sma50:
                md.append(
                    f"| 50-Day Moving Average | {sym}{sma50:.2f} | Short-term trend reference |"
                )
            if sma200:
                md.append(
                    f"| 200-Day Moving Average | {sym}{sma200:.2f} | Long-term trend reference |"
                )
            if bb_upper:
                md.append(f"| Bollinger Upper Band | {sym}{bb_upper:.2f} | Overbought zone |")
            if bb_lower:
                md.append(f"| Bollinger Lower Band | {sym}{bb_lower:.2f} | Oversold zone |")
            md.append("")

            # MA cross status
            if sma50 and sma200:
                if sma50 > sma200:
                    md.append(
                        "**Trend:** 50-day MA is ABOVE 200-day MA (Golden Cross — typically bullish)"
                    )
                else:
                    md.append(
                        "**Trend:** 50-day MA is BELOW 200-day MA (Death Cross — typically bearish)"
                    )
                md.append("")

        # Momentum summary
        if latest_vals:
            rsi = latest_vals.get("RSI_14")
            macd = latest_vals.get("MACD_12_26")
            macd_sig = latest_vals.get("MACD_Signal")
            adx = latest_vals.get("ADX_14")
            md.append("### Momentum & Trend Strength")
            md.append("")
            if rsi is not None:
                rsi_note = (
                    "oversold — potential bounce"
                    if rsi < 30
                    else "overbought — potential pullback"
                    if rsi > 70
                    else "neutral territory"
                )
                md.append(f"- **RSI (14):** {rsi:.1f} — {rsi_note}")
            if adx is not None:
                adx_note = (
                    "no clear trend"
                    if adx < 20
                    else "trend developing"
                    if adx < 25
                    else "strong trend"
                    if adx < 40
                    else "very strong trend"
                )
                md.append(f"- **ADX (14):** {adx:.1f} — {adx_note}")
            if macd is not None and macd_sig is not None:
                macd_dir = "above signal (bullish)" if macd > macd_sig else "below signal (bearish)"
                md.append(f"- **MACD:** {macd:.4f}, Signal: {macd_sig:.4f} — {macd_dir}")
            md.append("")

        # Volume
        if tech_stats:
            avg_vol = tech_stats.get("avg_volume")
            latest_vol = tech_stats.get("current_volume")
            if avg_vol and latest_vol:
                vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1
                vol_note = (
                    "well above average (high interest)"
                    if vol_ratio > 1.5
                    else "above average"
                    if vol_ratio > 1.1
                    else "near average"
                    if vol_ratio > 0.7
                    else "below average (low interest)"
                )
                md.append(f"**Volume:** {latest_vol:,.0f} ({vol_note}, avg: {avg_vol:,.0f})")
                md.append("")

    # ===== FUNDAMENTAL ANALYSIS =====
    fund_data = data.get("fundamental_analysis", {})
    if fund_data:
        md.append("---")
        md.append("")
        md.append("## Fundamental Analysis")
        md.append("")
        md.append(
            "> Fundamentals measure the financial health and operational performance of the business itself,"
        )
        md.append("> independent of its stock price movement.")
        md.append("")

        analysis = fund_data.get("analysis", fund_data)

        # Growth
        growth = analysis.get("growth_rates", {})
        rev = growth.get("revenue", {})
        earn = growth.get("earnings", {})
        fcf_g = growth.get("fcf", {})

        if any([rev, earn, fcf_g]):
            md.append("### Growth")
            md.append("")
            md.append("| Metric | 1 Year | 3 Year (CAGR) |")
            md.append("|--------|--------|---------------|")
            if rev:
                r1 = f"{rev['1y']:+.1f}%" if rev.get("1y") is not None else "N/A"
                r3 = f"{rev['3y_cagr']:+.1f}%" if rev.get("3y_cagr") is not None else "N/A"
                md.append(f"| Revenue | {r1} | {r3} |")
            if earn:
                e1 = f"{earn['1y']:+.1f}%" if earn.get("1y") is not None else "N/A"
                e3 = f"{earn['3y_cagr']:+.1f}%" if earn.get("3y_cagr") is not None else "N/A"
                md.append(f"| Earnings | {e1} | {e3} |")
            if fcf_g:
                f1 = f"{fcf_g['1y']:+.1f}%" if fcf_g.get("1y") is not None else "N/A"
                f3 = f"{fcf_g['3y_cagr']:+.1f}%" if fcf_g.get("3y_cagr") is not None else "N/A"
                md.append(f"| Free Cash Flow | {f1} | {f3} |")
            md.append("")

        # Margins
        margins = analysis.get("margins", {}).get("current", {})
        if margins:
            md.append("### Profitability")
            md.append("")
            md.append("| Margin | Value | Meaning |")
            md.append("|--------|-------|---------|")
            if margins.get("gross_margin") is not None:
                gm = margins["gross_margin"]
                gm_note = (
                    "strong pricing power"
                    if gm > 60
                    else "healthy"
                    if gm > 40
                    else "thin"
                    if gm > 20
                    else "very thin"
                )
                md.append(f"| Gross Margin | {gm:.1f}% | {gm_note.title()} |")
            if margins.get("operating_margin") is not None:
                om = margins["operating_margin"]
                om_note = (
                    "excellent operations"
                    if om > 25
                    else "healthy"
                    if om > 10
                    else "tight"
                    if om > 0
                    else "operating at a loss"
                )
                md.append(f"| Operating Margin | {om:.1f}% | {om_note.title()} |")
            if margins.get("net_margin") is not None:
                nm = margins["net_margin"]
                nm_note = (
                    "highly profitable"
                    if nm > 20
                    else "solid"
                    if nm > 10
                    else "modest"
                    if nm > 0
                    else "unprofitable"
                )
                md.append(f"| Net Margin | {nm:.1f}% | {nm_note.title()} |")
            md.append("")

        # Quality Scores
        quality = analysis.get("quality_scores", {})
        if quality:
            md.append("### Financial Quality & Integrity")
            md.append("")
            md.append(
                "> These scores detect problems that standard metrics miss — bankruptcy risk,"
            )
            md.append(
                "> earnings manipulation, and whether reported profits are backed by real cash."
            )
            md.append("")

            z = quality.get("altman_z")
            if z:
                model = quality.get("altman_model") or "Z"
                distress, safe = altman_zones(model)
                z_note = (
                    "Safe zone — low bankruptcy risk"
                    if z > safe
                    else "Grey zone — some financial stress"
                    if z > distress
                    else "DISTRESS zone — elevated bankruptcy risk"
                )
                md.append(f"- **Altman {model}-Score: {z:.2f}** — {z_note}")

            f_score = quality.get("piotroski_f")
            if f_score is not None:
                f_note = (
                    "Strong fundamentals"
                    if f_score >= 8
                    else "Average"
                    if f_score >= 5
                    else "Weak fundamentals"
                )
                md.append(f"- **Piotroski F-Score: {f_score}/9** — {f_note}")

            beneish = quality.get("beneish_m")
            if beneish and isinstance(beneish, dict) and beneish.get("m_score") is not None:
                m = beneish["m_score"]
                m_note = (
                    "Low manipulation risk"
                    if m < -2.22
                    else "Inconclusive (grey zone)"
                    if m < -1.78
                    else "HIGH manipulation risk — earnings may be inflated"
                )
                md.append(f"- **Beneish M-Score: {m:.2f}** — {m_note}")

            accruals = quality.get("accruals_quality")
            if (
                accruals
                and isinstance(accruals, dict)
                and accruals.get("accrual_ratio_pct") is not None
            ):
                ratio = accruals["accrual_ratio_pct"]
                interp = accruals.get("interpretation", "")
                md.append(f"- **Accruals Ratio: {ratio:.1f}%** — {interp}")

            cash_conv = quality.get("cash_conversion")
            if (
                cash_conv
                and isinstance(cash_conv, dict)
                and cash_conv.get("conversion_ratio_pct") is not None
            ):
                conv = cash_conv["conversion_ratio_pct"]
                conv_note = (
                    "excellent cash generation"
                    if conv > 100
                    else "healthy"
                    if conv >= 80
                    else "some cash leakage"
                    if conv >= 60
                    else "poor — significant gap between earnings and cash"
                )
                md.append(f"- **Cash Conversion: {conv:.0f}%** — {conv_note.title()}")
                if cash_conv.get("persistent_poor_conversion"):
                    md.append("  - WARNING: Persistently poor conversion over multiple years")

            md.append("")

        # DuPont
        dupont = analysis.get("dupont", {})
        if dupont and dupont.get("roe_calculated"):
            md.append("### ROE Decomposition (DuPont)")
            md.append("")
            md.append(
                "> Breaks Return on Equity into its three drivers to see WHERE profitability comes from."
            )
            md.append("")
            md.append(
                f"- Net Margin: {dupont.get('net_margin', 0):.1f}% (how much revenue becomes profit)"
            )
            md.append(
                f"- Asset Turnover: {dupont.get('asset_turnover', 0):.2f}x (how efficiently assets generate revenue)"
            )
            md.append(
                f"- Equity Multiplier: {dupont.get('equity_multiplier', 0):.2f}x (how much leverage is used)"
            )
            md.append(f"- **Resulting ROE: {dupont['roe_calculated']:.1f}%**")
            md.append("")

    # ===== RISK ANALYSIS =====
    risk_data = data.get("risk_analysis", {})
    if risk_data:
        md.append("---")
        md.append("")
        md.append("## Risk Analysis")
        md.append("")

        # Regime
        regime = risk_data.get("regime", {})
        if regime:
            md.append(f"**Current Market Regime: {regime.get('regime', 'unknown').upper()}**")
            md.append(f"*{regime.get('description', '')}*")
            md.append("")

        # Returns and volatility
        returns = risk_data.get("returns", {})
        vol = risk_data.get("volatility", {})
        if returns or vol:
            md.append("### Performance & Volatility")
            md.append("")
            md.append("| Metric | Value | Context |")
            md.append("|--------|-------|---------|")
            if returns.get("annualized_return") is not None:
                md.append(
                    f"| Annualized Return | {returns['annualized_return']:.1%} | Total return extrapolated to one year |"
                )
            if returns.get("win_rate") is not None:
                md.append(
                    f"| Win Rate | {returns['win_rate']:.0%} | Percentage of positive trading days |"
                )
            if vol.get("annualized_volatility") is not None:
                av = vol["annualized_volatility"]
                vol_ctx = (
                    "very high (>50%)"
                    if av > 0.5
                    else "elevated (30-50%)"
                    if av > 0.3
                    else "moderate (15-30%)"
                    if av > 0.15
                    else "low (<15%)"
                )
                md.append(f"| Annualized Volatility | {av:.1%} | {vol_ctx.title()} |")
            if vol.get("downside_deviation") is not None:
                md.append(
                    f"| Downside Deviation | {vol['downside_deviation']:.1%} | Volatility of losses only |"
                )
            md.append("")

        # Risk-adjusted ratios
        sharpe = risk_data.get("sharpe_ratio", 0)
        sortino = risk_data.get("sortino_ratio", 0)
        calmar = risk_data.get("calmar_ratio", 0)

        md.append("### Risk-Adjusted Performance")
        md.append("")
        md.append("> These ratios measure return PER UNIT OF RISK. Higher is always better.")
        md.append("")
        md.append("| Ratio | Value | Rating | What it measures |")
        md.append("|-------|-------|--------|------------------|")
        sharpe_rating = (
            "Excellent"
            if sharpe > 2
            else "Good"
            if sharpe > 1
            else "Acceptable"
            if sharpe > 0.5
            else "Poor"
            if sharpe > 0
            else "Negative"
        )
        md.append(f"| Sharpe | {sharpe:.2f} | {sharpe_rating} | Return per unit of total risk |")
        sortino_rating = (
            "Excellent"
            if sortino > 3
            else "Good"
            if sortino > 1.5
            else "Acceptable"
            if sortino > 0.5
            else "Poor"
        )
        md.append(
            f"| Sortino | {sortino:.2f} | {sortino_rating} | Return per unit of downside risk |"
        )
        calmar_rating = (
            "Excellent"
            if calmar > 3
            else "Good"
            if calmar > 1
            else "Weak"
            if calmar > 0
            else "Negative"
        )
        md.append(f"| Calmar | {calmar:.2f} | {calmar_rating} | Return divided by worst drawdown |")
        md.append("")

        # Drawdown
        dd = risk_data.get("drawdown", {})
        if dd:
            md.append("### Drawdown")
            md.append("")
            md.append(f"- **Maximum drawdown:** {dd.get('max_drawdown', 0):.1%}")
            if dd.get("max_drawdown_date"):
                md.append(f"  - Occurred: {dd['max_drawdown_date']}")
            curr_dd = dd.get("current_drawdown", 0)
            if dd.get("is_recovered"):
                md.append("- **Status:** Recovered to prior peak")
            elif curr_dd == curr_dd:  # NaN check
                md.append(
                    f"- **Current drawdown:** {curr_dd:.1%} ({dd.get('days_since_peak', 0)} days below peak)"
                )
            if dd.get("recovery_days"):
                md.append(f"- **Previous recovery:** took {dd['recovery_days']} days")
            md.append("")

        # Market risk
        mr = risk_data.get("market_risk", {})
        if mr:
            md.append("### Market Sensitivity")
            md.append("")
            beta_val = mr.get("beta", 0)
            alpha_val = mr.get("alpha", 0)
            corr_val = mr.get("correlation", 0)
            md.append(
                f"- **Beta: {beta_val:.2f}** — stock moves ~{beta_val:.1f}x the market on average"
            )
            if alpha_val > 0:
                md.append(
                    f"- **Alpha: {alpha_val:.1%}** — outperforming what its risk level predicts"
                )
            else:
                md.append(
                    f"- **Alpha: {alpha_val:.1%}** — underperforming what its risk level predicts"
                )
            bench = benchmark_name(mr.get("benchmark"))
            md.append(f"- **Correlation to {bench}:** {corr_val:.0%}")
            md.append(
                f"- **R-squared:** {mr.get('r_squared', 0):.0%} (how much of movement is explained by market)"
            )
            md.append("")

        # VaR
        var95 = risk_data.get("var_95", {})
        if var95:
            md.append("### Tail Risk (Value at Risk)")
            md.append("")
            md.append(
                f"- On a bad day (5% probability): loss of **{abs(var95.get('var_historical', 0)):.1%}** or more"
            )
            var99 = risk_data.get("var_99", {})
            if var99:
                md.append(
                    f"- On a very bad day (1% probability): loss of **{abs(var99.get('var_historical', 0)):.1%}** or more"
                )
                md.append(f"- Worst actual day in period: **{var99.get('worst_day', 0):.1%}**")
            md.append("")

        # Distribution
        dist = risk_data.get("distribution", {})
        if dist:
            md.append("### Return Distribution")
            md.append("")
            skew = dist.get("skewness", 0)
            kurt = dist.get("excess_kurtosis", 0)
            is_normal = dist.get("is_normally_distributed", True)
            md.append(f"- **Skewness: {skew:.2f}** — {dist.get('skew_interpretation', 'N/A')}")
            md.append(
                f"- **Excess Kurtosis: {kurt:.2f}** — {dist.get('kurtosis_interpretation', 'N/A')}"
            )
            if not is_normal:
                md.append(
                    "- Returns are NOT normally distributed — standard risk models may understate true risk"
                )
                tail_ratio = dist.get("tail_risk_ratio")
                if tail_ratio and tail_ratio > 1.3:
                    md.append(
                        f"- Actual extreme losses are {tail_ratio:.1f}x worse than a normal model predicts"
                    )
            md.append("")

        # Kelly
        kelly = risk_data.get("kelly_criterion")
        if kelly:
            md.append("### Position Sizing (Kelly Criterion)")
            md.append("")
            md.append(f"- Win rate: {kelly.get('win_rate', 0):.0%} of days positive")
            md.append(f"- Payoff ratio: {kelly.get('payoff_ratio', 0):.2f}x (avg win / avg loss)")
            kelly_pct = kelly.get("kelly_pct", 0)
            half_kelly = kelly.get("half_kelly_pct", 0)
            if kelly_pct > 0:
                md.append(
                    f"- **Recommended allocation (half-Kelly): {half_kelly:.1f}% of portfolio**"
                )
            else:
                md.append("- Kelly is negative — no statistical edge for position sizing")
            md.append(f"- Assessment: {kelly.get('description', '')}")
            md.append("")

    # ===== VALUATION =====
    val_data = data.get("valuation_analysis", {})
    if val_data:
        md.append("---")
        md.append("")
        md.append("## Valuation")
        md.append("")

        # DCF
        dcf = val_data.get("dcf_valuation", {})
        if dcf and not dcf.get("error") and dcf.get("intrinsic_value_per_share"):
            intrinsic = dcf["intrinsic_value_per_share"]
            discount = dcf.get("discount_premium_pct", 0)
            md.append("### DCF (Discounted Cash Flow)")
            md.append("")
            md.append("> Projects future free cash flows and discounts them back to present value.")
            md.append("")
            md.append("| Parameter | Value |")
            md.append("|-----------|-------|")
            md.append(f"| Intrinsic Value | {sym}{intrinsic:,.2f} |")
            if current_price:
                md.append(f"| Current Price | {sym}{current_price:.2f} |")
            if discount:
                direction = "undervalued" if discount < 0 else "overvalued"
                md.append(f"| Assessment | {abs(discount):.1f}% {direction} |")
            if dcf.get("growth_rate_used"):
                md.append(f"| Growth Rate | {dcf['growth_rate_used']:.1f}% |")
            if dcf.get("wacc_used"):
                md.append(f"| Discount Rate (WACC) | {dcf['wacc_used']:.1f}% |")
            md.append("")
        elif dcf and dcf.get("error"):
            md.append(f"**DCF:** Not applicable — {dcf['error']}")
            md.append("")

        # Monte Carlo
        mc = val_data.get("monte_carlo_valuation", {})
        if mc and not mc.get("error") and mc.get("probability_undervalued") is not None:
            md.append("### Monte Carlo Valuation (10,000 Simulations)")
            md.append("")
            md.append(
                "> Runs thousands of scenarios with varying growth, discount rates, and terminal values"
            )
            md.append(
                "> to produce a probability distribution of fair values rather than a single estimate."
            )
            md.append("")
            prob = mc["probability_undervalued"]
            md.append(f"**Probability stock is undervalued: {prob:.0%}**")
            md.append("")
            scenarios = mc.get("scenarios", {})
            ci = mc.get("confidence_intervals", {})
            if scenarios:
                md.append("| Scenario | Fair Value | vs. Current |")
                md.append("|----------|-----------|-------------|")
                for label, val in [
                    ("Bear (10th percentile)", scenarios.get("bear_case")),
                    ("Base (median)", scenarios.get("base_case")),
                    ("Bull (90th percentile)", scenarios.get("bull_case")),
                ]:
                    if val is not None and current_price:
                        diff = ((val - current_price) / current_price) * 100
                        md.append(f"| {label} | {sym}{val:,.2f} | {diff:+.0f}% |")
                    elif val is not None:
                        md.append(f"| {label} | {sym}{val:,.2f} | — |")
                md.append("")
            if ci:
                md.append(
                    f"50% confidence range: {sym}{ci.get('ci_25', 0):,.2f} – {sym}{ci.get('ci_75', 0):,.2f}"
                )
                md.append("")
        elif mc and mc.get("error"):
            md.append(f"**Monte Carlo:** Not applicable — {mc['error']}")
            md.append("")

        # DDM
        ddm = val_data.get("ddm_valuation", {})
        if ddm and not ddm.get("error") and ddm.get("intrinsic_value_per_share"):
            intrinsic = ddm["intrinsic_value_per_share"]
            md.append("### Dividend Discount Model")
            md.append("")
            md.append(f"- Intrinsic value: {sym}{intrinsic:,.2f}")
            if ddm.get("growth_rate_used"):
                md.append(f"- Dividend growth assumption: {ddm['growth_rate_used']:.1f}%")
            md.append("")

        # Earnings
        earnings = val_data.get("earnings_analysis", {})
        if earnings and earnings.get("current_eps"):
            md.append("### Earnings")
            md.append("")
            md.append(f"- Current EPS (TTM): {sym}{earnings['current_eps']:.2f}")
            if earnings.get("forward_eps"):
                md.append(f"- Forward EPS (analyst est.): {sym}{earnings['forward_eps']:.2f}")
            if earnings.get("eps_growth_1y"):
                md.append(f"- EPS growth (1Y): {earnings['eps_growth_1y']:+.1f}%")
            if earnings.get("trend"):
                md.append(f"- Trend: {earnings['trend']}")
            md.append("")

    # ===== ANALYST CONSENSUS =====
    ratings = data.get("analyst_ratings")
    if ratings and ratings.get("recommendations"):
        recs = ratings["recommendations"]
        if isinstance(recs, list) and len(recs) > 0:
            latest_rec = recs[0] if isinstance(recs[0], dict) else {}
            total = sum(
                latest_rec.get(k, 0) for k in ["strongBuy", "buy", "hold", "sell", "strongSell"]
            )
            if total > 0:
                md.append("---")
                md.append("")
                md.append("## Analyst Consensus")
                md.append("")
                buys = latest_rec.get("strongBuy", 0) + latest_rec.get("buy", 0)
                holds = latest_rec.get("hold", 0)
                sells = latest_rec.get("sell", 0) + latest_rec.get("strongSell", 0)
                md.append(f"**{buys} Buy** | {holds} Hold | {sells} Sell (from {total} analysts)")
                md.append("")

                # Recent upgrades/downgrades
                upgrades = ratings.get("upgrades_downgrades")
                if upgrades and isinstance(upgrades, list) and len(upgrades) > 0:
                    md.append("| Firm | Action | Rating | Target |")
                    md.append("|------|--------|--------|--------|")
                    for ug in upgrades[:5]:
                        if isinstance(ug, dict):
                            firm = ug.get("Firm", "N/A")
                            action = ug.get("Action", "")
                            to_grade = ug.get("ToGrade", "")
                            target = ug.get("target", "")
                            target_str = f"{sym}{target}" if target else "—"
                            md.append(f"| {firm} | {action} | {to_grade} | {target_str} |")
                    md.append("")

    # ===== INSTITUTIONAL OWNERSHIP =====
    holders = data.get("holders")
    if holders and holders.get("institutional_holders"):
        inst = holders["institutional_holders"]
        if isinstance(inst, list) and len(inst) > 0:
            md.append("---")
            md.append("")
            md.append("## Top Institutional Holders")
            md.append("")
            md.append("| Institution | % Held |")
            md.append("|-------------|--------|")
            for h in inst[:5]:
                if isinstance(h, dict):
                    name = h.get("Holder", "N/A")
                    pct = h.get("pctHeld", 0)
                    if pct:
                        md.append(f"| {name} | {pct:.2%} |")
            md.append("")

    # ===== RECENT NEWS =====
    news = data.get("news")
    if news and isinstance(news, list) and len(news) > 0:
        md.append("---")
        md.append("")
        md.append("## Recent News")
        md.append("")
        for article in news[:5]:
            if isinstance(article, dict):
                title = article.get("title", "")
                url = article.get("url", "")
                publisher = article.get("publisher", "")
                if title:
                    if url:
                        md.append(f"- [{title}]({url}) — *{publisher}*")
                    else:
                        md.append(f"- {title} — *{publisher}*")
        md.append("")

    return "\n".join(md)
