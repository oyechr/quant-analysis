"""
LLM integration for generating plain-English investment briefs from TOON reports.

Supports Anthropic (Claude) and OpenAI (GPT). Provider is inferred from the
model name: claude-* -> Anthropic, gpt-*/o*-* -> OpenAI.

Configure in config.json:
    {
        "llm_model": "claude-haiku-3-5",
        "llm_anthropic_api_key": "sk-ant-...",
        "llm_openai_api_key": "sk-..."
    }

Default model (claude-haiku-3-5) costs ~$0.004 per call at typical report size.
Use claude-sonnet-4-5 or gpt-4.1 for richer analysis at ~5x cost.
"""

import json
import logging
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a buy-side equity analyst reviewing a structured quantitative report.

The report contains:
- A composite score (0-100) and dimension scores: Technical, Fundamental, Risk, Valuation
- Key strengths and concerns flagged by the scoring engine
- Technical indicators (RSI, MACD, moving averages, Bollinger Bands, ADX, etc.)
- Fundamental metrics (revenue/earnings growth, margins, Piotroski F-Score, Altman Z-Score)
- Risk metrics (Sharpe ratio, Sortino, max drawdown, VaR, beta)
- Valuation models (DCF intrinsic value, DDM, FCF yield, earnings quality)

Write a concise investment brief with these sections:
1. **Company snapshot** (1-2 sentences: what the company does and its current market position)
2. **Score interpretation** (what the composite and dimension scores imply about the setup)
3. **Key strengths** (top 2-3, with specific numbers from the report)
4. **Key risks** (top 2-3 that could invalidate the thesis)
5. **Valuation** (cheap / fair / expensive - reference DCF/DDM/FCF yield where available)
6. **Conclusion** (Buy / Hold / Avoid with a one-sentence rationale)

Be direct and specific. Use numbers from the report. No disclaimers. Max 450 words."""


def _infer_provider(model: str) -> str:
    """Infer LLM provider from model name."""
    m = model.lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "openai"
    return "anthropic"


def _fmt(value: Any, pct: bool = False, decimals: int = 1) -> str:
    """Format a numeric value or return 'N/A'."""
    if value is None:
        return "N/A"
    try:
        f = float(value)
        return f"{f:.{decimals}f}{'%' if pct else ''}"
    except (TypeError, ValueError):
        return str(value)


def build_brief_context(report_data: Dict[str, Any]) -> str:
    """
    Build a focused context string (~1,500 tokens) from a full report dict.

    Strips time-series data, raw indicator history, holders, and detailed
    DCF workings. Keeps scoring, key fundamentals, risk metrics, valuation
    results, technical signals, earnings beats, and analyst consensus.

    Args:
        report_data: Parsed full_report.json dict.

    Returns:
        Compact context string for the LLM prompt.
    """
    lines = []

    # --- Company identity ---
    info = report_data.get("info") or {}
    lines += [
        f"TICKER: {report_data.get('ticker', 'N/A')}",
        f"Company: {info.get('name', 'N/A')}",
        f"Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')}",
        f"Price: {_fmt(info.get('current_price') or (report_data.get('technical_analysis') or {}).get('latest_values', {}).get('close_price'))}  "
        f"Market cap: {_fmt(info.get('market_cap'), decimals=0)}",
        "",
    ]

    # --- Composite score & dimensions ---
    scoring = report_data.get("scoring") or {}
    lines += [
        "=== SCORING ===",
        f"Composite: {_fmt(scoring.get('composite_score'))}/100  Signal: {scoring.get('signal', 'N/A')}  "
        f"Confidence: {scoring.get('confidence', 'N/A')} ({_fmt((scoring.get('confidence_score') or 0) * 100)}%)",
    ]
    dims = scoring.get("dimensions") or scoring.get("dimension_scores") or {}
    for dim_name, dim in dims.items():
        if not isinstance(dim, dict):
            continue
        score = _fmt(dim.get("score"))
        coverage = _fmt((dim.get("data_coverage") or 0) * 100, pct=True, decimals=0)
        lines.append(f"  {dim_name.capitalize()}: {score}/100  [{coverage} data]")
        for sub in (dim.get("sub_scores") or []):
            lines.append(f"    {sub.get('name')}: {_fmt(sub.get('score'))}/100  "
                         f"raw={_fmt(sub.get('raw_value'), decimals=2)}  ({sub.get('label', '')})")
    strengths = scoring.get("strengths") or []
    concerns = scoring.get("concerns") or []
    if strengths:
        lines.append(f"Strengths: {'; '.join(strengths)}")
    if concerns:
        lines.append(f"Concerns: {'; '.join(concerns)}")
    lines.append("")

    # --- Key valuation ratios from info ---
    lines += [
        "=== VALUATION RATIOS ===",
        f"P/E: {_fmt(info.get('pe_ratio'))}  Forward P/E: {_fmt(info.get('forward_pe'))}  "
        f"PEG: {_fmt(info.get('peg_ratio'))}  P/B: {_fmt(info.get('price_to_book'))}  P/S: {_fmt(info.get('price_to_sales'))}",
        f"Dividend yield: {_fmt(info.get('dividend_yield'))}%  Beta: {_fmt(info.get('beta'))}  "
        f"52w range: {_fmt(info.get('52w_low'))} - {_fmt(info.get('52w_high'))}",
        "",
    ]

    # --- Fundamental analysis ---
    fa = (report_data.get("fundamental_analysis") or {}).get("analysis") or {}
    growth = fa.get("growth_rates") or {}
    fcf_m = fa.get("fcf_metrics") or {}
    margins = (fa.get("margins") or {}).get("current") or {}
    quality = fa.get("quality_scores") or {}
    dupont = fa.get("dupont") or {}
    lines += [
        "=== FUNDAMENTALS ===",
        f"Revenue growth 1y: {_fmt(growth.get('revenue', {}).get('1y'))}%  "
        f"3y CAGR: {_fmt(growth.get('revenue', {}).get('3y_cagr'))}%",
        f"Earnings growth 1y: {_fmt(growth.get('earnings', {}).get('1y'))}%  "
        f"3y CAGR: {_fmt(growth.get('earnings', {}).get('3y_cagr'))}%",
        f"FCF growth 1y: {_fmt(growth.get('fcf', {}).get('1y'))}%  "
        f"FCF yield: {_fmt(fcf_m.get('fcf_yield'))}%  FCF margin: {_fmt(fcf_m.get('fcf_margin'))}%",
        f"Gross margin: {_fmt(margins.get('gross_margin'))}%  "
        f"Operating margin: {_fmt(margins.get('operating_margin'))}%  "
        f"Net margin: {_fmt(margins.get('net_margin'))}%",
        f"ROE: {_fmt(dupont.get('roe_reported'))}%  Asset turnover: {_fmt(dupont.get('asset_turnover'))}",
        f"Piotroski F-Score: {quality.get('piotroski_f', 'N/A')}/9  "
        f"Altman Z-Score: {_fmt(quality.get('altman_z'))}",
        "",
    ]

    # --- Risk metrics (key ratios only, no rolling history) ---
    ra = report_data.get("risk_analysis") or {}
    vol = ra.get("volatility") or {}
    dd = ra.get("drawdown") or {}
    mr = ra.get("market_risk") or {}
    var95 = ra.get("var_95") or {}
    lines += [
        "=== RISK ===",
        f"Ann. volatility: {_fmt((vol.get('annualized_volatility') or 0) * 100)}%  "
        f"Sharpe: {_fmt(ra.get('sharpe_ratio'))}  Sortino: {_fmt(ra.get('sortino_ratio'))}  "
        f"Calmar: {_fmt(ra.get('calmar_ratio'))}",
        f"Max drawdown: {_fmt((dd.get('max_drawdown') or 0) * 100)}%  "
        f"Current drawdown: {_fmt((dd.get('current_drawdown') or 0) * 100)}%",
        f"Beta vs {mr.get('benchmark', '^GSPC')}: {_fmt(mr.get('beta'))}  "
        f"Alpha: {_fmt(mr.get('alpha'))}  Correlation: {_fmt(mr.get('correlation'))}",
        f"VaR 95% (historical): {_fmt((var95.get('var_historical') or 0) * 100)}%/day  "
        f"CVaR: {_fmt((var95.get('cvar_historical') or 0) * 100)}%/day",
        "",
    ]

    # --- Valuation models ---
    va = report_data.get("valuation_analysis") or {}
    dcf = va.get("dcf_valuation") or {}
    ddm = va.get("ddm_valuation") or {}
    div = va.get("dividend_analysis") or {}
    earn = va.get("earnings_analysis") or {}
    lines += ["=== VALUATION MODELS ==="]
    if dcf:
        lines.append(
            f"DCF intrinsic value: {_fmt(dcf.get('intrinsic_value_per_share'))}  "
            f"Current price: {_fmt(dcf.get('current_price'))}  "
            f"Premium to DCF: {_fmt(dcf.get('discount_premium_pct'))}%"
        )
    if ddm:
        lines.append(
            f"DDM value: {_fmt(ddm.get('intrinsic_value'))}  "
            f"Premium to DDM: {_fmt(ddm.get('discount_premium_pct'))}%"
        )
    if div:
        lines.append(
            f"Div yield: {_fmt(div.get('yield_pct'))}%  "
            f"Payout ratio: {_fmt(div.get('payout_ratio_pct'))}%  "
            f"Sustainability: {div.get('sustainability_label', 'N/A')}"
        )
    if earn:
        lines.append(
            f"EPS quality: {earn.get('quality_label', 'N/A')}  "
            f"Beat rate: {_fmt(earn.get('beat_rate_pct'))}%"
        )
    lines.append("")

    # --- Technical signals (current state only, no indicator history) ---
    ta = report_data.get("technical_analysis") or {}
    signals = ta.get("signals") or {}
    if signals:
        lines.append("=== TECHNICAL SIGNALS ===")
        for k, v in signals.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    # --- Analyst consensus ---
    ar = report_data.get("analyst_ratings") or {}
    recs = ar.get("recent_recommendations") or []
    changes = ar.get("recent_upgrade_downgrade") or []
    if recs:
        lines.append("=== ANALYST CONSENSUS ===")
        latest = recs[0] if recs else {}
        sb = latest.get("strongBuy", 0)
        b = latest.get("buy", 0)
        h = latest.get("hold", 0)
        s = latest.get("sell", 0)
        ss = latest.get("strongSell", 0)
        lines.append(f"Current: StrongBuy={sb} Buy={b} Hold={h} Sell={s} StrongSell={ss}")
    if changes:
        lines.append("Recent changes (latest 5):")
        for c in changes[:5]:
            lines.append(
                f"  {c.get('GradeDate', '')[:10]}  {c.get('Firm', '')}  "
                f"{c.get('Action', '')}  {c.get('FromGrade', '')} -> {c.get('ToGrade', '')}"
            )
    lines.append("")

    # --- Latest earnings beats ---
    earnings = report_data.get("earnings") or {}
    history = earnings.get("earnings_history") or []
    if history:
        lines.append("=== RECENT EARNINGS ===")
        for e in history[:4]:
            surprise = _fmt(e.get("surprisePercent"), pct=True) if e.get("surprisePercent") is not None else "N/A"
            lines.append(
                f"  {e.get('quarter', '')}  EPS actual={_fmt(e.get('epsActual'))}  "
                f"estimate={_fmt(e.get('epsEstimate'))}  surprise={surprise}"
            )

    return "\n".join(lines)


def explain(
    toon_text: str,
    model: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> str:
    """
    Generate a plain-English investment brief from a TOON report.

    Streams tokens to stdout as they arrive, then returns the full text.

    Args:
        toon_text: TOON-formatted report content.
        model: Model name override (e.g. 'gpt-4o'). Reads llm_model from
               config.json if not provided.
        anthropic_api_key: Override for Anthropic key (else reads config).
        openai_api_key: Override for OpenAI key (else reads config).

    Returns:
        Full narrative as a string.

    Raises:
        ValueError: API key not configured.
        ImportError: Required provider package not installed.
    """
    from .config import get_config

    config = get_config()
    resolved_model = model or config.llm_model
    provider = _infer_provider(resolved_model)

    if provider == "anthropic":
        key = anthropic_api_key or config.llm_anthropic_api_key
        if not key:
            raise ValueError(
                "Anthropic API key not configured.\n"
                "Add 'llm_anthropic_api_key' to config.json."
            )
        return _stream_anthropic(toon_text, resolved_model, key)

    # For OpenAI-compatible models: prefer GitHub Models (free) when token is
    # configured; fall back to direct OpenAI API.
    github_token = config.llm_github_token
    if github_token:
        return _stream_github(toon_text, resolved_model, github_token)

    key = openai_api_key or config.llm_openai_api_key
    if not key:
        raise ValueError(
            "No LLM credentials configured.\n"
            "Add 'llm_github_token' (free, recommended) or 'llm_openai_api_key' to config.json.\n"
            "GitHub token: https://github.com/settings/tokens (no special scopes needed)"
        )
    return _stream_openai(toon_text, resolved_model, key)


def _stream_anthropic(toon_text: str, model: str, api_key: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)
    tokens = []

    with client.messages.stream(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": toon_text}],
    ) as stream:
        for text in stream.text_stream:
            sys.stdout.write(text)
            sys.stdout.flush()
            tokens.append(text)

    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(tokens)


def _stream_github(toon_text: str, model: str, github_token: str) -> str:
    """Stream via GitHub Models free tier (OpenAI SDK, different base URL)."""
    try:
        import openai
    except ImportError:
        raise ImportError(
            "openai package not installed. Run: pip install openai"
        )
    return _stream_openai(
        toon_text,
        model,
        api_key=github_token,
        base_url="https://models.inference.ai.azure.com",
    )


def _stream_openai(
    toon_text: str, model: str, api_key: str, base_url: Optional[str] = None
) -> str:
    try:
        import openai
    except ImportError:
        raise ImportError(
            "openai package not installed. Run: pip install openai"
        )

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    tokens = []

    try:
        stream = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": toon_text},
            ],
            stream=True,
        )
    except openai.AuthenticationError as e:
        raise ValueError(f"OpenAI authentication failed - check your API key. ({e})") from e
    except openai.RateLimitError as e:
        raise ValueError(
            "OpenAI quota exceeded. Add billing credits at https://platform.openai.com/billing"
        ) from e
    except openai.APIError as e:
        raise ValueError(f"OpenAI API error: {e}") from e
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content or ""
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
                tokens.append(text)
    except Exception as e:
        raise ValueError(f"OpenAI streaming error: {e}") from e

    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(tokens)
