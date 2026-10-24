"""Single-ticker and multi-ticker analysis: report, score, vet, compare, watch."""

import time
from pathlib import Path

import click

from ..comparison import (
    PortfolioView,
    TickerComparator,
    calculate_risk_parity_weights,
    format_comparison_json,
    format_comparison_markdown,
    format_comparison_table,
    format_correlation_heatmap,
    format_diversification,
    format_portfolio_view,
    identify_correlation_flags,
)
from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from ..reporting import ReportGenerator
from ..scoring import format_score_table
from ..utils.concurrency import run_concurrently
from .common import (
    config_option,
    echo_freshness_warnings,
    get_scoring_config,
    record_history,
    workers_option,
)


@click.command()
@click.argument("ticker")
@click.option("--exclude-technical", is_flag=True, help="Exclude technical analysis.")
@click.option("--exclude-fundamental", is_flag=True, help="Exclude fundamental analysis.")
@click.option("--exclude-risk", is_flag=True, help="Exclude risk analysis.")
@click.option("--exclude-valuation", is_flag=True, help="Exclude valuation analysis.")
@config_option()
@click.pass_context
def report(
    ctx,
    ticker,
    exclude_technical,
    exclude_fundamental,
    exclude_risk,
    exclude_valuation,
    config_name,
):
    """Generate a full report and detailed scorecard for a single ticker.

    Prints the complete scorecard breakdown (dimension scores, strengths,
    concerns) and saves json/md/toon report files.
    Use 'score' instead when screening multiple tickers at once.

    Example: quant report AAPL --period 2y --config value
    """
    output_dir = ctx.obj["output_dir"]
    output_format = ctx.obj["output_format"]

    ticker = ticker.upper()
    generator = ReportGenerator(output_dir=output_dir)

    click.echo("=" * 70)
    click.echo(f"  Generating report for {ticker}")
    click.echo("=" * 70)

    bundle = generator.generate(
        ticker,
        AnalysisOptions(
            period=ctx.obj["period"],
            use_cache=ctx.obj["use_cache"],
            include_technical=not exclude_technical,
            include_fundamental=not exclude_fundamental,
            include_risk=not exclude_risk,
            include_valuation=not exclude_valuation,
            scoring_config=get_scoring_config(config_name),
        ),
        output_format=output_format,
    )

    click.echo(f"\nReport generated for {ticker}")
    if output_format in ("json", "all"):
        click.echo(f"  - JSON: {output_dir}/{ticker}/reports/full_report.json")
    if output_format in ("markdown", "all"):
        click.echo(f"  - Markdown: {output_dir}/{ticker}/reports/report.md")
    if output_format in ("toon", "all"):
        click.echo(f"  - TOON: {output_dir}/{ticker}/reports/full_report.toon")

    echo_freshness_warnings(ticker, bundle.report)

    if bundle.scoring:
        from ..tracking import history_row

        record_history(output_dir, [history_row(bundle.report, bundle.scoring, "report")])
        click.echo()
        click.echo(bundle.scoring.format_scorecard())

    click.echo(f"\nFiles saved in: {output_dir}/{ticker}/reports/")


@click.command()
@click.argument("tickers", nargs=-1, required=True)
@config_option()
@workers_option()
@click.pass_context
def score(ctx, tickers, config_name, workers):
    """Score one or more tickers and display a summary table.

    Prints a compact one-row-per-ticker table with composite score, signal,
    and dimension breakdown. Use 'report' for a single-ticker deep dive,
    or 'screen' to rank a whole index.

    Example: quant score AAPL MSFT TSLA --config value
    """
    from ..tracking import history_row

    output_format = ctx.obj["output_format"]
    generator = ReportGenerator(output_dir=ctx.obj["output_dir"])
    options = AnalysisOptions(
        period=ctx.obj["period"],
        use_cache=ctx.obj["use_cache"],
        scoring_config=get_scoring_config(config_name),
    )
    tickers_list = list(dict.fromkeys(t.upper() for t in tickers))

    click.echo(f"  Analyzing {len(tickers_list)} ticker(s)...")
    results = {}
    history = []
    for ticker, bundle, error in run_concurrently(
        lambda t: generator.generate(t, options, output_format=output_format),
        tickers_list,
        workers=workers,
    ):
        if error is not None or bundle.scoring is None:
            click.echo(f"  ✗ Error for {ticker}: {error or 'scoring failed'}", err=True)
            results[ticker] = None
            continue
        echo_freshness_warnings(ticker, bundle.report)
        results[ticker] = bundle.scoring
        history.append(history_row(bundle.report, bundle.scoring, "score"))
    record_history(ctx.obj["output_dir"], history)

    click.echo(format_score_table({t: results.get(t) for t in tickers_list}, config_name))


@click.command()
@click.argument("ticker")
@click.option(
    "--peers",
    default=None,
    help="Comma-separated peer tickers (default: Yahoo's industry/sector list, similar size).",
)
@config_option()
@click.option("--brief", is_flag=True, help="Only the verdict, key facts, and next steps.")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
@click.option(
    "--save", is_flag=True, help="Also write <output-dir>/<TICKER>/reports/vet.json and vet.md."
)
@click.pass_context
def vet(ctx, ticker, peers, config_name, brief, as_json, save):
    """One-screen verdict: should TICKER get a deeper look?

    Shows the score, red flags, valuation against peers, earnings drift and
    relative strength, 13F fund activity, fair value range, and the price at
    which the signal would change. Nothing is written unless --save is given.

    Automatic peers come from Yahoo's industry list (its sector list if fewer
    than 4 remain), filtered to 0.1x-10x the ticker's market cap. Yahoo's lists
    are mostly US companies; pass --peers for home-market peers.

    \b
    Examples:
      quant vet EQNR.OL
      quant vet EQNR.OL --brief
      quant vet AAPL --peers MSFT,GOOGL,META
      quant vet EQNR.OL --peers AKRBP.OL,VAR.OL
      quant vet NVDA --config growth --save
    """
    import json as _json

    from ..vetting import render_markdown, render_text, vet_ticker

    output_dir = ctx.obj["output_dir"]
    ticker = ticker.upper()
    peer_list = [p.strip().upper() for p in (peers or "").split(",") if p.strip()]

    if not as_json:
        click.echo(f"  Vetting {ticker}...", err=True)
    result = vet_ticker(
        ticker,
        fetcher=DataFetcher(cache_dir=output_dir),
        options=AnalysisOptions(
            period=ctx.obj["period"],
            use_cache=ctx.obj["use_cache"],
            include_context=False,
            scoring_config=get_scoring_config(config_name),
        ),
        peers=peer_list or None,
        data_dir=output_dir,
    )
    if not (result.report.get("info") or {}) and result.bundle.scoring is None:
        raise click.ClickException(f"No data for {ticker}. Check the symbol (e.g. EQNR.OL).")

    from ..tracking import history_row

    record_history(
        output_dir, [history_row(result.report, result.base_scoring, "vet", result.red_flags)]
    )
    data = result.to_dict()
    if as_json:
        click.echo(_json.dumps(data, indent=2, default=str))
    else:
        click.echo(render_text(data, brief=brief))

    if save:
        reports_dir = Path(output_dir) / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "vet.json").write_text(
            _json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        (reports_dir / "vet.md").write_text(render_markdown(data), encoding="utf-8")
        click.echo(f"  Saved: {reports_dir / 'vet.json'}, {reports_dir / 'vet.md'}", err=True)


@click.command()
@click.argument("tickers", nargs=-1, required=True)
@config_option()
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

    Shows scoring comparison, relative valuation, correlation matrix,
    highly correlated pairs and hedges, and risk-parity suggested weights.

    Example: quant compare AAPL MSFT GOOGL --weights 0.5,0.3,0.2
    """
    if len(tickers) < 2:
        raise click.UsageError("At least 2 tickers are required for comparison.")

    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
    period = ctx.obj["period"]
    output_format = ctx.obj["output_format"]

    scoring_config = get_scoring_config(config_name)
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

    # Diversification: correlated pairs/hedges and inverse-volatility weights
    correlation_flags = None
    risk_parity = None
    try:
        if corr_df is not None and not corr_df.empty:
            correlation_flags = identify_correlation_flags(corr_df)
        risk_parity = calculate_risk_parity_weights(comparator.price_data(use_cache=use_cache))
    except Exception as e:
        click.echo(f"  ✗ Diversification analysis failed: {e}", err=True)

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
                correlation_flags=correlation_flags,
                risk_parity=risk_parity,
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
        click.echo(format_diversification(correlation_flags, risk_parity, markdown=True))
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
        click.echo(format_diversification(correlation_flags, risk_parity))

    if portfolio_stats:
        click.echo(format_portfolio_view(portfolio_stats))


@click.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--interval", default=300, type=int, help="Refresh interval in seconds (default: 300)."
)
@click.option("--count", default=0, type=int, help="Number of iterations (default: 0 = infinite).")
@config_option()
@click.pass_context
def watch(ctx, tickers, interval, count, config_name):
    """Continuously watch and score tickers at regular intervals (intraday).

    Re-fetches data every iteration; nothing is written to disk.
    Press Ctrl-C to stop. For a daily check of what moved since the last
    run, use `quant changes` instead.

    Example: quant watch AAPL MSFT --interval 60 --count 5
    """
    period = ctx.obj["period"]
    generator = ReportGenerator(output_dir=ctx.obj["output_dir"])
    options = AnalysisOptions(
        period=period,
        use_cache=False,
        include_context=False,
        scoring_config=get_scoring_config(config_name),
    )
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
                    result = generator.generate(ticker, options, output_format="none").scoring
                    if result is None:
                        raise RuntimeError("scoring failed")
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
