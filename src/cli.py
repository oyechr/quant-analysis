"""
CLI Interface for Quantitative Analysis Tool

Provides subcommands: report, score, compare, explain, watch
Install with: pip install -e .
Usage: quant report AAPL
"""

import logging
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import click

from .comparison import (
    PortfolioView,
    TickerComparator,
    format_comparison_json,
    format_comparison_markdown,
    format_comparison_table,
    format_correlation_heatmap,
)
from .reporting import ReportGenerator
from .scoring import ScoringConfig, StockScorer


def _configure_logging(verbose: bool, quiet: bool):
    """Set up logging based on verbosity flags."""
    # Ensure UTF-8 output on Windows where the default console encoding (cp1252)
    # cannot represent the Unicode block characters used in scorecards.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", force=True)


def _get_scoring_config(config_name: str) -> ScoringConfig:
    """Resolve a scoring config preset by name."""
    presets = {
        "default": ScoringConfig,
        "value": ScoringConfig.value_investor,
        "growth": ScoringConfig.growth_investor,
        "income": ScoringConfig.income_investor,
    }
    factory = presets.get(config_name)
    if factory is None:
        raise click.BadParameter(
            f"Unknown config preset '{config_name}'. Available: {', '.join(presets.keys())}"
        )
    return factory()


@click.group()
@click.option("--output-dir", default="data", help="Output directory for reports and data.")
@click.option("--no-cache", is_flag=True, default=False, help="Fetch fresh data (ignore cache).")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "markdown", "toon", "all"], case_sensitive=False),
    default="all",
    help="Output format (default: all).",
)
@click.option("--period", default="1y", help="Data period (e.g., 1mo, 3mo, 6mo, 1y, 2y, 5y).")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable debug logging.")
@click.option("-q", "--quiet", is_flag=True, default=False, help="Suppress info logging.")
@click.pass_context
def cli(ctx, output_dir, no_cache, output_format, period, verbose, quiet):
    """Quantitative stock analysis tool.

    Analyze, score, compare, and watch stocks from the command line.
    """
    _configure_logging(verbose, quiet)
    ctx.ensure_object(dict)
    ctx.obj["output_dir"] = output_dir
    ctx.obj["use_cache"] = not no_cache
    ctx.obj["output_format"] = output_format
    ctx.obj["period"] = period


@cli.command()
@click.argument("ticker")
@click.option("--exclude-technical", is_flag=True, help="Exclude technical analysis.")
@click.option("--exclude-fundamental", is_flag=True, help="Exclude fundamental analysis.")
@click.option("--exclude-risk", is_flag=True, help="Exclude risk analysis.")
@click.option("--exclude-valuation", is_flag=True, help="Exclude valuation analysis.")
@click.pass_context
def report(ctx, ticker, exclude_technical, exclude_fundamental, exclude_risk, exclude_valuation):
    """Generate a full report and detailed scorecard for a single ticker.

    Prints the complete scorecard breakdown (dimension scores, strengths,
    concerns) and saves json/md/toon report files.
    Use 'score' instead when screening multiple tickers at once.

    Example: quant report AAPL --period 2y
    """
    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
    output_format = ctx.obj["output_format"]
    period = ctx.obj["period"]

    ticker = ticker.upper()
    generator = ReportGenerator(output_dir=output_dir)

    click.echo("=" * 70)
    click.echo(f"  Generating report for {ticker}")
    click.echo("=" * 70)

    report_data = generator.generate_full_report(
        ticker=ticker,
        period=period,
        output_format=output_format,
        use_cache=use_cache,
        include_technical=not exclude_technical,
        include_fundamental=not exclude_fundamental,
        include_risk=not exclude_risk,
        include_valuation=not exclude_valuation,
    )

    click.echo(f"\nReport generated for {ticker}")
    if output_format in ("json", "all"):
        click.echo(f"  - JSON: {output_dir}/{ticker}/reports/full_report.json")
    if output_format in ("markdown", "all"):
        click.echo(f"  - Markdown: {output_dir}/{ticker}/reports/report.md")
    if output_format in ("toon", "all"):
        click.echo(f"  - TOON: {output_dir}/{ticker}/reports/full_report.toon")

    # Display scorecard
    scoring_data = report_data.get("scoring")
    if scoring_data:
        scorer = StockScorer()
        scoring_result = scorer.score(report_data)
        click.echo()
        click.echo(scoring_result.format_scorecard())

    click.echo(f"\nFiles saved in: {output_dir}/{ticker}/reports/")


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--config",
    "config_name",
    type=click.Choice(["default", "value", "growth", "income"], case_sensitive=False),
    default="default",
    help="Scoring preset (default, value, growth, income).",
)
@click.pass_context
def score(ctx, tickers, config_name):
    """Score one or more tickers and display a summary table.

    Prints a compact one-row-per-ticker table with composite score, signal,
    and dimension breakdown. Use 'report' for a single-ticker deep dive.

    Example: quant score AAPL MSFT TSLA --config value
    """
    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
    output_format = ctx.obj["output_format"]
    period = ctx.obj["period"]

    scoring_config = _get_scoring_config(config_name)
    generator = ReportGenerator(output_dir=output_dir)
    scorer = StockScorer(config=scoring_config)

    results: List[Tuple[str, Optional[object]]] = []

    for ticker in tickers:
        ticker = ticker.upper()
        click.echo(f"  Analyzing {ticker}...")
        try:
            report_data = generator.generate_full_report(
                ticker=ticker,
                period=period,
                output_format=output_format,
                use_cache=use_cache,
            )
            result = scorer.score(report_data)
            results.append((ticker, result))
        except Exception as e:
            click.echo(f"  ✗ Error for {ticker}: {e}", err=True)
            results.append((ticker, None))

    # Print summary table
    click.echo()
    click.echo("=" * 70)
    click.echo(f"  STOCK SCORES  (preset: {config_name})")
    click.echo("=" * 70)
    click.echo()
    click.echo(
        f"  {'Ticker':<8} {'Score':>6} {'Signal':<12} {'Confidence':<10} {'Tech':>5} "
        f"{'Fund':>5} {'Risk':>5} {'Val':>5}"
    )
    click.echo("  " + "-" * 62)

    for ticker, result in results:
        if result is None:
            click.echo(f"  {ticker:<8}    ERROR")
            continue
        tech = f"{result.technical.score:.0f}" if result.technical else "N/A"
        fund = f"{result.fundamental.score:.0f}" if result.fundamental else "N/A"
        risk = f"{result.risk.score:.0f}" if result.risk else "N/A"
        val = f"{result.valuation.score:.0f}" if result.valuation else "N/A"
        click.echo(
            f"  {ticker:<8} {result.composite_score:>5.0f}  {result.signal:<12} "
            f"{result.confidence:<10} {tech:>5} {fund:>5} {risk:>5} {val:>5}"
        )

    click.echo()


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--config",
    "config_name",
    type=click.Choice(["default", "value", "growth", "income"], case_sensitive=False),
    default="default",
    help="Scoring preset.",
)
@click.option(
    "--save-chart",
    default=None,
    type=str,
    help="Save correlation heatmap to this file path (e.g., data/corr.png).",
)
@click.option(
    "--weights",
    default=None,
    type=str,
    help="Comma-separated portfolio weights (e.g., 0.5,0.3,0.2).",
)
@click.pass_context
def compare(ctx, tickers, config_name, save_chart, weights):
    """Compare two or more tickers side-by-side.

    Shows scoring comparison, relative valuation, and correlation matrix.

    Example: quant compare AAPL MSFT GOOGL --weights 0.5,0.3,0.2
    """
    if len(tickers) < 2:
        raise click.UsageError("At least 2 tickers are required for comparison.")

    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
    period = ctx.obj["period"]
    output_format = ctx.obj["output_format"]

    scoring_config = _get_scoring_config(config_name)
    tickers_list = [t.upper() for t in tickers]

    click.echo("=" * 70)
    click.echo(f"  Comparing: {', '.join(tickers_list)}")
    click.echo("=" * 70)

    comparator = TickerComparator(
        tickers=tickers_list,
        period=period,
        scoring_config=scoring_config,
        output_dir=output_dir,
        output_format=output_format,
    )

    click.echo("\n  Fetching data...")
    comparator.fetch_all(use_cache=use_cache)

    click.echo("  Scoring...")
    comparator.score_all()

    # Side-by-side scores
    try:
        scores_df = comparator.side_by_side_scores()
    except RuntimeError:
        scores_df = None

    # Relative valuation
    try:
        valuation_df = comparator.relative_valuation()
    except RuntimeError:
        valuation_df = None

    # Key metrics
    try:
        metrics_df = comparator.key_metrics_table()
    except RuntimeError:
        metrics_df = None

    # Correlation matrix
    try:
        corr_df = comparator.correlation_matrix(use_cache=use_cache)
    except Exception:
        corr_df = None

    # Portfolio view
    portfolio_stats = None
    if weights:
        try:
            weight_list = [float(w.strip()) for w in weights.split(",")]
            pv = PortfolioView(tickers=tickers_list, weights=weight_list)
            portfolio_stats = pv.portfolio_stats(comparator)
        except Exception as e:
            click.echo(f"  ✗ Portfolio error: {e}", err=True)

    # Output
    if output_format == "json":
        click.echo(
            format_comparison_json(
                scores_df=scores_df,
                valuation_df=valuation_df,
                correlation_df=corr_df,
                metrics_df=metrics_df,
                portfolio_stats=portfolio_stats,
            )
        )
    elif output_format == "markdown":
        if scores_df is not None:
            click.echo(format_comparison_markdown(scores_df, title="Score Comparison"))
        if valuation_df is not None:
            click.echo(format_comparison_markdown(valuation_df, title="Relative Valuation"))
        if metrics_df is not None:
            click.echo(format_comparison_markdown(metrics_df, title="Key Metrics"))
        if corr_df is not None:
            click.echo(format_comparison_markdown(corr_df, title="Correlation Matrix"))
    else:
        # Table / all format
        if scores_df is not None:
            click.echo(format_comparison_table(scores_df, title="SCORE COMPARISON"))
        if valuation_df is not None:
            click.echo(format_comparison_table(valuation_df, title="RELATIVE VALUATION"))
        if metrics_df is not None:
            click.echo(format_comparison_table(metrics_df, title="KEY METRICS"))
        if corr_df is not None:
            click.echo(format_correlation_heatmap(corr_df, save_path=save_chart))

    # Portfolio summary
    if portfolio_stats:
        click.echo()
        click.echo("=" * 70)
        click.echo("  PORTFOLIO VIEW")
        click.echo("=" * 70)
        ws = portfolio_stats.get("weighted_composite_score")
        wb = portfolio_stats.get("weighted_beta")
        dr = portfolio_stats.get("diversification_ratio")
        click.echo(f"  Weighted Score: {ws}" if ws else "  Weighted Score: N/A")
        click.echo(f"  Weighted Beta:  {wb}" if wb else "  Weighted Beta:  N/A")
        click.echo(f"  Diversification Ratio: {dr}" if dr else "  Diversification Ratio: N/A")
        click.echo()
        for h in portfolio_stats.get("holdings", []):
            sig = h.get("signal", "N/A")
            sc = h.get("score", "N/A")
            click.echo(f"  {h['ticker']:<8} weight={h['weight']:.1%}  score={sc}  signal={sig}")
        click.echo()


@cli.command()
@click.argument("ticker")
@click.option(
    "--model",
    default=None,
    help="LLM model override (e.g. gpt-4o, claude-sonnet-4-5). Reads llm_model from config.json if not set.",
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
        { "llm_anthropic_api_key": "sk-ant-...", "llm_model": "claude-haiku-3-5" }

    Example: quant chat EQNR
    Example: quant chat AAPL --model claude-sonnet-4-5 --no-intro
    """
    import json as _json

    from .llm import build_brief_context
    from .llm import chat_turn as llm_chat_turn

    ticker = ticker.upper()
    output_dir = ctx.obj["output_dir"]
    period = ctx.obj["period"]
    use_cache = ctx.obj["use_cache"]
    json_path = Path(output_dir) / ticker / "reports" / "full_report.json"

    def _load_report(force_refresh: bool = False):
        if force_refresh or not json_path.exists():
            click.echo(f"  Generating report for {ticker}...")
            generator = ReportGenerator(output_dir=output_dir)
            generator.generate_full_report(
                ticker=ticker,
                period=period,
                output_format="all",
                use_cache=(not force_refresh) and use_cache,
            )
        if not json_path.exists():
            raise click.ClickException(f"Failed to generate report for {ticker}.")
        return _json.loads(json_path.read_text(encoding="utf-8"))

    report_data = _load_report()
    context = build_brief_context(report_data)

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
        except (EOFError, KeyboardInterrupt):
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
                context = build_brief_context(report_data)
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


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--interval", default=300, type=int, help="Refresh interval in seconds (default: 300)."
)
@click.option("--count", default=0, type=int, help="Number of iterations (default: 0 = infinite).")
@click.option(
    "--config",
    "config_name",
    type=click.Choice(["default", "value", "growth", "income"], case_sensitive=False),
    default="default",
    help="Scoring preset.",
)
@click.pass_context
def watch(ctx, tickers, interval, count, config_name):
    """Continuously watch and score tickers at regular intervals.

    Press Ctrl-C to stop.

    Example: quant watch AAPL MSFT --interval 60 --count 5
    """
    output_dir = ctx.obj["output_dir"]
    period = ctx.obj["period"]
    output_format = ctx.obj["output_format"]

    scoring_config = _get_scoring_config(config_name)
    generator = ReportGenerator(output_dir=output_dir)
    scorer = StockScorer(config=scoring_config)
    tickers_list = [t.upper() for t in tickers]

    iteration = 0
    try:
        while True:
            iteration += 1
            if count > 0 and iteration > count:
                break

            click.clear()
            click.echo("=" * 70)
            click.echo(f"  WATCH MODE  -  Iteration {iteration}{'/' + str(count) if count else ''}")
            click.echo(f"  Refresh: {interval}s | Period: {period} | Preset: {config_name}")
            click.echo("=" * 70)
            click.echo()
            click.echo(f"  {'Ticker':<8} {'Score':>6} {'Signal':<12} {'Confidence':<10}")
            click.echo("  " + "-" * 40)

            for ticker in tickers_list:
                try:
                    report_data = generator.generate_full_report(
                        ticker=ticker,
                        period=period,
                        output_format=output_format,
                        use_cache=False,
                    )
                    result = scorer.score(report_data)
                    click.echo(
                        f"  {ticker:<8} {result.composite_score:>5.0f}  "
                        f"{result.signal:<12} {result.confidence:<10}"
                    )
                except Exception as e:
                    click.echo(f"  {ticker:<8}   ERROR: {e}")

            if count > 0 and iteration >= count:
                break

            click.echo(f"\n  Next refresh in {interval}s... (Ctrl-C to stop)")
            time.sleep(interval)

    except KeyboardInterrupt:
        click.echo("\n  Watch stopped.")


if __name__ == "__main__":
    cli()
