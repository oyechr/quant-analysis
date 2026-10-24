"""Interactive analyst chat: chat."""

import logging
from datetime import date
from pathlib import Path

import click

from ..reporting import ReportGenerator

CHAT_HISTORY_ROWS = 12  # score history rows given to `quant chat`


@click.command()
@click.argument("ticker")
@click.option(
    "--model",
    default=None,
    help="LLM model override (e.g. gpt-4o, claude-opus-5-5). Reads llm_model from config.json if not set.",
)
@click.option(
    "--no-intro",
    is_flag=True,
    default=False,
    help="Skip the automatic opening investment brief and go straight to the prompt.",
)
@click.option(
    "--debug-context",
    is_flag=True,
    default=False,
    help="Print the context sent to the LLM and exit without starting the chat.",
)
@click.pass_context
def chat(ctx, ticker, model, no_intro, debug_context):
    """Interactive analyst chat session for a single ticker.

    Loads (or generates) the full report for TICKER, then opens a
    conversational session where you can interrogate the stock data.
    The LLM has the full quantitative context for every question.

    Special commands (type during the session):
      /refresh   Re-fetch fresh data and rebuild the report
      /clear     Reset conversation history (context is always preserved)
      /help      Show available commands
      /quit      Exit the session

    Configure API keys in config.json:
        { "llm_anthropic_api_key": "sk-ant-...", "llm_model": "claude-haiku-5-5" }

    Example: quant chat EQNR
    Example: quant chat AAPL --model claude-opus-5-5 --no-intro
    """
    import json as _json

    from ..llm import build_brief_context
    from ..llm import chat_turn as llm_chat_turn

    ticker = ticker.upper()
    output_dir = ctx.obj["output_dir"]
    period = ctx.obj["period"]
    use_cache = ctx.obj["use_cache"]
    json_path = Path(output_dir) / ticker / "reports" / "full_report.json"

    def _read_report():
        try:
            return _json.loads(json_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None

    def _load_report(force_refresh: bool = False):
        report = None if force_refresh else _read_report()
        # A report from an earlier day is rebuilt, so the chat never sees old prices
        if report is None or str(report.get("generated_at", ""))[:10] < date.today().isoformat():
            click.echo(f"  Generating report for {ticker}...")
            generator = ReportGenerator(output_dir=output_dir)
            generator.generate_full_report(
                ticker=ticker,
                period=period,
                output_format="all",
                use_cache=(not force_refresh) and use_cache,
            )
            report = _read_report()
        if report is None:
            raise click.ClickException(f"Failed to generate report for {ticker}.")
        return report

    def _build_context(report: dict) -> str:
        from ..tracking import load_history

        # Peers come from the last `quant vet --save`, so chat startup stays offline
        peers = None
        vet_path = Path(output_dir) / ticker / "reports" / "vet.json"
        if vet_path.exists():
            try:
                peers = _json.loads(vet_path.read_text(encoding="utf-8")).get("peer_valuation")
            except (OSError, ValueError) as e:
                logging.getLogger(__name__).warning(f"Peer context unavailable: {e}")
        history = load_history(output_dir, ticker)[-CHAT_HISTORY_ROWS:]
        return build_brief_context(report, peer_valuation=peers, score_history=history)

    report_data = _load_report()
    context = _build_context(report_data)

    if debug_context:
        click.echo(context)
        return

    ticker_name = (report_data.get("info") or {}).get("name", ticker)
    click.echo()
    click.echo("=" * 70)
    click.echo(f"  Chat: {ticker} — {ticker_name}")
    click.echo("  Commands: /refresh  /clear  /help  /quit")
    click.echo("=" * 70)
    click.echo()

    messages = []

    if not no_intro:
        intro = (
            "Give me a concise investment brief: company snapshot, score interpretation, "
            "top 2-3 strengths, top 2-3 risks, valuation assessment, and a buy/hold/avoid conclusion."
        )
        click.echo("  Assistant:\n")
        try:
            response = llm_chat_turn(context, [{"role": "user", "content": intro}], model=model)
            messages.append({"role": "user", "content": intro})
            messages.append({"role": "assistant", "content": response})
        except (ValueError, ImportError) as e:
            raise click.ClickException(str(e))
        click.echo()

    while True:
        try:
            user_input = click.prompt("  You", prompt_suffix=" > ").strip()
        except EOFError, KeyboardInterrupt:
            click.echo("\n  Session ended.")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "quit", "exit"):
            click.echo("  Session ended.")
            break

        if cmd == "/clear":
            messages.clear()
            click.echo("  Conversation history cleared.\n")
            continue

        if cmd == "/help":
            click.echo("  /refresh  — re-fetch fresh data and rebuild the report")
            click.echo("  /clear    — reset conversation history (context is preserved)")
            click.echo("  /quit     — exit the session\n")
            continue

        if cmd == "/refresh":
            click.echo("  Re-fetching data...")
            try:
                report_data = _load_report(force_refresh=True)
                context = _build_context(report_data)
                messages.clear()
                click.echo("  Data refreshed. Conversation history cleared.\n")
            except Exception as e:
                click.echo(f"  Refresh failed: {e}\n")
            continue

        messages.append({"role": "user", "content": user_input})
        click.echo("\n  Assistant:\n")

        try:
            response = llm_chat_turn(context, messages, model=model)
            messages.append({"role": "assistant", "content": response})
        except (ValueError, ImportError) as e:
            click.echo(f"\n  Error: {e}")
            messages.pop()

        click.echo()
