"""
LLM integration for `quant chat`: a conversation about one ticker's report.

The provider follows the model name: claude-* goes to Anthropic, and every
other name (gpt-4.1, o4-mini, ...) goes to OpenAI.

Configure in config.json:
    {
        "llm_model": "claude-haiku-5-5",
        "llm_anthropic_api_key": "sk-ant-...",
        "llm_openai_api_key": "sk-..."
    }

The default model is claude-haiku-5-5, the cheap option (well under a cent per
brief); claude-opus-5-5 gives richer analysis at about 40x the price. GitHub
Models, the old free default, was retired by GitHub on 2026-07-30.

Every provider error reaches the caller as a ValueError with a readable
message, so a failed turn never ends the chat session.
"""

import logging
import sys
from typing import Any, Dict, List, Optional, cast

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """You are a buy-side equity analyst assistant. You have been given a structured quantitative report for a specific stock.

Report data:
---
{context}
---

Answer questions about this stock using the data above. Be specific and cite numbers from the report. When asked about hypothetical scenarios (e.g. "what if growth drops to 2%?"), reason through the implications clearly using the provided metrics. If asked for a full investment brief or summary, structure it as: company snapshot, score interpretation, key strengths, key risks, valuation, and buy/hold/avoid conclusion. Be direct and concise. No disclaimers."""


class LLMConfigError(ValueError):
    """No credentials for the chosen provider: retrying won't help."""


def _infer_provider(model: str) -> str:
    """Anthropic for claude-* models; every other name is OpenAI-compatible."""
    return "anthropic" if model.lower().startswith("claude") else "openai"


def _fmt(value: Any, pct: bool = False, decimals: int = 1) -> str:
    """Format a numeric value or return 'N/A'."""
    if value is None:
        return "N/A"
    try:
        f = float(value)
        return f"{f:.{decimals}f}{'%' if pct else ''}"
    except TypeError, ValueError:
        return str(value)


def build_brief_context(
    report_data: Dict[str, Any],
    red_flags: Optional[List[Dict[str, Any]]] = None,
    peer_valuation: Optional[Dict[str, Any]] = None,
    score_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Build a focused context string (~1,500 tokens) from a full report dict.

    Strips time-series data, raw indicator history, holders, and detailed
    DCF workings. Keeps scoring, red flags, peer valuation, key fundamentals,
    risk metrics, valuation results, technical signals, earnings beats, and
    analyst consensus.

    Args:
        report_data: Parsed full_report.json dict.
        red_flags: Red flags as dicts; computed from the report when omitted.
        peer_valuation: Peer comparison dict (vetting.PeerValuation.to_dict());
            defaults to the report's own `peer_valuation` if present.
        score_history: Earlier score history rows (tracking.load_history), oldest
            first, so the model can explain how the score has moved.

    Returns:
        Compact context string for the LLM prompt.
    """
    if red_flags is None:
        from .vetting import find_red_flags

        red_flags = [f.to_dict() for f in find_red_flags(report_data)]
    peer_valuation = peer_valuation or report_data.get("peer_valuation")

    lines = []

    # --- Company identity ---
    info = report_data.get("info") or {}
    lines += [
        f"TICKER: {report_data.get('ticker', 'N/A')}",
        f"Company: {info.get('name', 'N/A')}",
        f"Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')}",
        f"Price: {_fmt(info.get('current_price') or (report_data.get('technical_analysis') or {}).get('latest_values', {}).get('close_price'))}  "
        f"Market cap: {_fmt(info.get('market_cap'), decimals=0)}",
        f"Report date: {str(report_data.get('generated_at') or 'N/A')[:10]}",
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
        for sub in dim.get("sub_scores") or []:
            lines.append(
                f"    {sub.get('name')}: {_fmt(sub.get('score'))}/100  "
                f"raw={_fmt(sub.get('raw_value'), decimals=2)}  ({sub.get('label', '')})"
            )
    strengths = scoring.get("strengths") or []
    concerns = scoring.get("concerns") or []
    if strengths:
        lines.append(f"Strengths: {'; '.join(strengths)}")
    if concerns:
        lines.append(f"Concerns: {'; '.join(concerns)}")
    lines.append("")

    # --- Score history ---
    if score_history:
        lines.append("=== SCORE HISTORY (oldest first; standard valuation cutoffs) ===")
        for row in score_history:
            dims = ", ".join(
                f"{name[:4]} {_fmt(row.get(name), decimals=0)}"
                for name in ("technical", "fundamental", "risk", "valuation")
            )
            flags = f"; red flags: {row['flags']}" if row.get("flags") else ""
            lines.append(
                f"  {row.get('date')} [{row.get('preset')}]: {_fmt(row.get('score'))} "
                f"{row.get('signal')} ({dims}) price {_fmt(row.get('price'))}{flags}"
            )
        lines.append("")

    # --- Red flags ---
    lines.append("=== RED FLAGS ===")
    if red_flags:
        for flag in red_flags:
            lines.append(f"  [{flag.get('severity')}] {flag.get('title')}: {flag.get('detail')}")
    else:
        lines.append("  None found")
    lines.append("")

    # --- Peer-relative valuation ---
    if peer_valuation and peer_valuation.get("peers"):
        group = f" in {peer_valuation['group']}" if peer_valuation.get("group") else ""
        lines.append(
            f"=== PEER VALUATION ({peer_valuation.get('basis')}{group}: "
            f"{', '.join(peer_valuation['peers'])}) ==="
        )
        for metric in (peer_valuation.get("metrics") or {}).values():
            if metric.get("value") is None and metric.get("median") is None:
                continue
            cheap = metric.get("cheapness")
            rank = f"cheaper than {cheap:.0f}% of peers" if cheap is not None else "no rank"
            lines.append(
                f"  {metric.get('label')}: {_fmt(metric.get('value'))} vs peer median "
                f"{_fmt(metric.get('median'))} ({rank}, n={metric.get('n', 0)})"
            )
        lines.append("")

    # --- Analyst price targets ---
    if info.get("target_mean_price"):
        lines.append(
            f"Analyst targets: mean {_fmt(info.get('target_mean_price'))} "
            f"(low {_fmt(info.get('target_low_price'))}, high {_fmt(info.get('target_high_price'))}, "
            f"n={info.get('analyst_count', 'N/A')})  Consensus: {info.get('recommendation_key', 'N/A')}"
        )
        lines.append("")

    # --- Signals outside the composite score ---
    signals = report_data.get("signals") or {}
    rs = signals.get("relative_strength")
    pead = signals.get("pead")
    if rs or pead:
        lines.append("=== MOMENTUM & EARNINGS SIGNALS ===")
        if rs:
            lines.append(
                f"  Relative strength vs {rs.get('benchmark') or 'benchmark'}: "
                f"{rs.get('rs_rating')}/99 ({rs.get('interpretation', '')})"
            )
        if pead:
            lines.append(
                f"  Post-earnings drift: {pead.get('signal')} (SUE {_fmt(pead.get('sue'), decimals=2)}; "
                f"{pead.get('interpretation', '')})"
            )
        lines.append("")

    # --- Key valuation ratios from info ---
    lines += [
        "=== VALUATION RATIOS ===",
        f"P/E: {_fmt(info.get('pe_ratio'))}  Forward P/E: {_fmt(info.get('forward_pe'))}  "
        f"PEG: {_fmt(info.get('peg_ratio'))}  P/B: {_fmt(info.get('price_to_book'))}  P/S: {_fmt(info.get('price_to_sales'))}",
        # Beta is left to the RISK section: Yahoo's is vs the S&P 500, ours vs the home index
        f"Dividend yield: {_fmt(info.get('dividend_yield'))}%  "
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
        f"Altman {quality.get('altman_model') or 'Z'}-Score: {_fmt(quality.get('altman_z'))}",
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
        f"Beta vs {mr.get('benchmark', 'benchmark')}: {_fmt(mr.get('beta'))}  "
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
            f"DDM value: {_fmt(ddm.get('intrinsic_value_per_share'))}  "
            f"Premium to DDM: {_fmt(ddm.get('discount_premium_pct'))}%"
        )
    if div:
        lines.append(
            f"Div yield: {_fmt(div.get('dividend_yield'), pct=True)}  "
            f"Payout ratio: {_fmt(div.get('payout_ratio'), pct=True)}  "
            f"Sustainability: {div.get('sustainability_rating') or 'N/A'}"
        )
    if earn:
        quality = earn.get("earnings_quality") or {}
        surprises = earn.get("surprise_stats") or {}
        lines.append(
            f"EPS quality: {quality.get('assessment') or 'N/A'}  "
            f"Beat rate: {_fmt(surprises.get('beat_rate'), pct=True)}"
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
    changes = ar.get("recent_changes") or []
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
                f"  {str(c.get('GradeDate') or '')[:10]}  {c.get('Firm', '')}  "
                f"{c.get('Action', '')}  {c.get('FromGrade', '')} -> {c.get('ToGrade', '')}"
            )
    lines.append("")

    # --- Latest earnings beats ---
    earnings = report_data.get("earnings") or {}
    history = earnings.get("earnings_history") or []
    if history:
        lines.append("=== RECENT EARNINGS ===")
        for e in history[:4]:
            surprise = (
                _fmt(e.get("surprisePercent"), pct=True)
                if e.get("surprisePercent") is not None
                else "N/A"
            )
            lines.append(
                f"  {e.get('quarter', '')}  EPS actual={_fmt(e.get('epsActual'))}  "
                f"estimate={_fmt(e.get('epsEstimate'))}  surprise={surprise}"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider settings
# ---------------------------------------------------------------------------

# Current Claude models think before answering, and thinking counts toward
# max_tokens, so leave room for both (the calls stream, so a large cap is safe).
ANTHROPIC_MAX_TOKENS = 16000
# OpenAI: room for a reasoning model's hidden reasoning plus the reply.
OPENAI_MAX_TOKENS = 16000


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _emit(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _note_stop_reason(reason: Optional[str]) -> None:
    """Say so when a reply was cut off or declined instead of ending normally.

    Anthropic says max_tokens/refusal; OpenAI-compatible APIs say
    length/content_filter.
    """
    if reason in ("max_tokens", "length"):
        _emit("\n  [Note: the reply hit the length limit and was cut off]")
    elif reason == "refusal":
        _emit("\n  [Note: the model declined to answer this request]")
    elif reason == "content_filter":
        _emit("\n  [Note: the provider's content filter stopped the reply]")


# ---------------------------------------------------------------------------
# Interactive chat
# ---------------------------------------------------------------------------


def chat_turn(
    context: str,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> str:
    """
    Send one conversational turn to the LLM and stream the response.

    The stock context is embedded in the system prompt so every turn has
    access to the full quantitative report data.

    Args:
        context: Compact context string from build_brief_context().
        messages: Full conversation history as list of {role, content} dicts.
                  The last entry should be the user's current message.
        model: Model name override. Reads llm_model from config.json if omitted.
        anthropic_api_key: Override for Anthropic key (else reads config).
        openai_api_key: Override for OpenAI key (else reads config).

    Returns:
        The assistant's reply text; empty when the model declined or wrote nothing.

    Raises:
        LLMConfigError: no credentials for the provider (a ValueError).
        ValueError: any API or network error.
        ImportError: the provider's package isn't installed.
    """
    from .config import get_config

    config = get_config()
    resolved_model = model or config.llm_model
    provider = _infer_provider(resolved_model)
    system = CHAT_SYSTEM_PROMPT.format(context=context)

    if provider == "anthropic":
        key = anthropic_api_key or config.llm_anthropic_api_key
        if not key:
            raise LLMConfigError(
                "Anthropic API key not configured.\nAdd 'llm_anthropic_api_key' to config.json."
            )
        return _chat_anthropic(system, messages, resolved_model, key)

    key = openai_api_key or config.llm_openai_api_key
    if not key:
        raise LLMConfigError(
            f"OpenAI API key not configured for {resolved_model}.\n"
            "Add 'llm_openai_api_key' to config.json, or set llm_model to a claude-* model "
            "with 'llm_anthropic_api_key'."
        )
    return _chat_openai(system, messages, resolved_model, key)


def _anthropic_error_message(e: Exception, model: str) -> str:
    """A readable message for an Anthropic SDK error.

    An error event inside a stream arrives as an APIStatusError with the
    stream's 200 status, so the error type in the body decides as well.
    """
    import anthropic

    body = getattr(e, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    status = getattr(e, "status_code", None)

    if isinstance(e, anthropic.AuthenticationError):
        return "Anthropic authentication failed - check llm_anthropic_api_key in config.json."
    if isinstance(e, anthropic.PermissionDeniedError):
        return f"Anthropic denied access to {model} - check the API key's permissions."
    if isinstance(e, anthropic.NotFoundError):
        return f"Anthropic has no model '{model}' - check llm_model in config.json or --model."
    if isinstance(e, anthropic.RateLimitError) or kind == "rate_limit_error":
        return "Anthropic rate limit hit - wait a minute and ask again."
    if kind == "overloaded_error" or status == 529:
        return "Anthropic is overloaded right now - ask again in a minute."
    if isinstance(e, anthropic.APITimeoutError):
        return "Anthropic didn't answer in time - ask again."
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach Anthropic - check the network connection."
    if kind == "api_error" or (isinstance(status, int) and status >= 500):
        return "Anthropic had a server error - ask again in a minute."
    if isinstance(e, anthropic.APIStatusError):
        return f"Anthropic API error ({e.status_code}): {e.message}"
    return f"Anthropic API error: {e}"


def _chat_anthropic(system: str, messages: List[Dict[str, str]], model: str, api_key: str) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("anthropic package not installed. Run: pip install anthropic") from e

    from anthropic.types import MessageParam

    client = anthropic.Anthropic(api_key=api_key)
    tokens = []

    # The SDK retries 429, 5xx and connection errors itself before this sees them
    try:
        with client.messages.stream(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=cast(List[MessageParam], messages),
        ) as stream:
            for text in stream.text_stream:
                _emit(text)
                tokens.append(text)
            stop_reason = stream.get_final_message().stop_reason
    except anthropic.APIError as e:
        raise ValueError(_anthropic_error_message(e, model)) from e

    _note_stop_reason(stop_reason)
    _emit("\n")
    return "".join(tokens)


def _chat_openai(system: str, messages: List[Dict[str, str]], model: str, api_key: str) -> str:
    try:
        import openai
    except ImportError as e:
        raise ImportError("openai package not installed. Run: pip install openai") from e

    from openai.types.chat import ChatCompletionMessageParam

    client = openai.OpenAI(api_key=api_key)
    full_messages = cast(
        List[ChatCompletionMessageParam],
        [{"role": "system", "content": system}, *messages],
    )
    tokens = []
    finish_reason: Optional[str] = None
    chunks = 0
    refusal = ""

    try:
        stream = client.chat.completions.create(
            model=model,
            messages=full_messages,
            stream=True,
            # max_tokens is rejected by reasoning models (o-series, gpt-5)
            max_completion_tokens=OPENAI_MAX_TOKENS,
        )
        for chunk in stream:
            chunks += 1
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            text = choice.delta.content or ""
            if text:
                _emit(text)
                tokens.append(text)
            refusal += getattr(choice.delta, "refusal", None) or ""
            if choice.finish_reason:
                finish_reason = choice.finish_reason
    except openai.AuthenticationError as e:
        raise ValueError(
            "OpenAI authentication failed - check llm_openai_api_key in config.json."
        ) from e
    except openai.RateLimitError as e:
        raise ValueError(
            "OpenAI quota exceeded. Add billing credits at https://platform.openai.com/billing"
        ) from e
    except openai.NotFoundError as e:
        raise ValueError(f"Unknown model '{model}' - check llm_model or --model. ({e})") from e
    except openai.APIError as e:
        raise ValueError(f"API error: {e}") from e

    if refusal:
        _emit(f"\n  [Note: the model declined: {refusal}]")
    elif not tokens and finish_reason in (None, "stop"):
        # Nothing to show and no reason given: say what did come back
        _emit(
            f"\n  [Note: {model} sent no text ({chunks} stream chunks, "
            f"finish reason {finish_reason or 'none'})]"
        )
    _note_stop_reason(finish_reason)
    _emit("\n")
    return "".join(tokens)
