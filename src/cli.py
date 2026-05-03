"""
CLI Interface for Quantitative Analysis Tool

Provides subcommands: analyze, score, compare, watch
Install with: pip install -e .
Usage: quant analyze AAPL
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
            f"Unknown config preset '{config_name}'. "
            f"Available: {', '.join(presets.keys())}"
        )
    return factory()


@click.group()
@click.option("--output-dir", default="data", help="Output directory for reports and data.")
@click.option("--no-cache", is_flag=True, default=False, help="Fetch fresh data (ignore cache).")
@click.option(
    "--format", "output_format",
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
def analyze(ctx, ticker, exclude_technical, exclude_fundamental, exclude_risk, exclude_valuation):
    """Generate a comprehensive analysis report for a single ticker.

    Example: quant analyze AAPL --period 2y
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

    click.echo(f"\n✓ Report generated for {ticker}")
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
    "--config", "config_name",
    type=click.Choice(["default", "value", "growth", "income"], case_sensitive=False),
    default="default",
    help="Scoring preset (default, value, growth, income).",
)
@click.pass_context
def score(ctx, tickers, config_name):
    """Score one or more tickers and display a summary table.

    Example: quant score AAPL MSFT TSLA --config value
    """
    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
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
                output_format="json",
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
    click.echo(f"  {'Ticker':<8} {'Score':>6} {'Signal':<12} {'Confidence':<10} {'Tech':>5} "
               f"{'Fund':>5} {'Risk':>5} {'Val':>5}")
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
    "--config", "config_name",
    type=click.Choice(["default", "value", "growth", "income"], case_sensitive=False),
    default="default",
    help="Scoring preset.",
)
@click.option("--save-chart", default=None, type=str,
              help="Save correlation heatmap to this file path (e.g., data/corr.png).")
@click.option("--weights", default=None, type=str,
              help="Comma-separated portfolio weights (e.g., 0.5,0.3,0.2).")
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
        click.echo(format_comparison_json(
            scores_df=scores_df,
            valuation_df=valuation_df,
            correlation_df=corr_df,
            metrics_df=metrics_df,
            portfolio_stats=portfolio_stats,
        ))
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
@click.argument("tickers", nargs=-1, required=True)
@click.option("--interval", default=300, type=int,
              help="Refresh interval in seconds (default: 300).")
@click.option("--count", default=0, type=int,
              help="Number of iterations (default: 0 = infinite).")
@click.option(
    "--config", "config_name",
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
            click.echo(f"  WATCH MODE — Iteration {iteration}"
                       f"{'/' + str(count) if count else ''}")
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
                        output_format="json",
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
