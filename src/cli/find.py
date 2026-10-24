"""Finding candidates: screen, discover."""

from pathlib import Path

import click

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from .common import (
    config_option,
    get_scoring_config,
    record_history,
    workers_option,
)


def _parse_amount_option(ctx, param, value):
    if value is None:
        return None
    from ..screening import parse_amount

    try:
        return parse_amount(value)
    except ValueError as e:
        raise click.BadParameter(str(e)) from e


@click.command()
@click.argument("universe", nargs=-1)
@click.option("--top", default=20, show_default=True, help="Candidates to fully score.")
@config_option()
@click.option(
    "--sector",
    "sectors",
    multiple=True,
    help="Keep only this sector/industry (substring, repeatable).",
)
@click.option(
    "--exclude-sector",
    "exclude_sectors",
    multiple=True,
    help="Drop this sector/industry (substring, repeatable).",
)
@click.option(
    "--min-mcap",
    callback=_parse_amount_option,
    help="Minimum market cap (e.g. 2B, 500M), in --currency.",
)
@click.option("--max-mcap", callback=_parse_amount_option, help="Maximum market cap.")
@click.option(
    "--currency",
    default=None,
    help="Currency of --min-mcap/--max-mcap (default: the universe's own; USD if it mixes).",
)
@click.option(
    "--min-volume",
    callback=_parse_amount_option,
    help="Minimum average daily volume in shares (e.g. 500K).",
)
@workers_option()
@click.option("--list", "list_only", is_flag=True, help="List built-in universes and exit.")
@click.option("--save/--no-save", default=True, show_default=True, help="Write results files.")
@click.option(
    "--add-to-watchlist",
    "add_top",
    type=click.IntRange(min=1),
    default=None,
    help="Add the N best-scoring results to watchlist.toml.",
)
@click.pass_context
def screen(
    ctx,
    universe,
    top,
    config_name,
    sectors,
    exclude_sectors,
    min_mcap,
    max_mcap,
    currency,
    min_volume,
    workers,
    list_only,
    save,
    add_top,
):
    """Screen an index or ticker list for the best candidates.

    UNIVERSE is one or more of: a built-in index (sp500, sp100, nasdaq100,
    obx), 'discover' (consensus picks from the last `quant discover` run),
    a path to a ticker file, or literal tickers. Mix freely.

    Stage 1 ranks every ticker on value, quality, momentum and low volatility
    using cheap data. Stage 2 runs the full analysis and composite score on
    the --top candidates.

    \b
    Examples:
      quant screen sp500 --top 25 --config value
      quant screen obx --exclude-sector Energy
      quant screen nasdaq100 --sector Technology --min-mcap 50B
      quant screen discover
      quant screen watchlist
      quant screen sp100 --add-to-watchlist 5
      quant screen tickers.txt EQNR.OL DNB.OL
    """
    from ..screening import (
        Screener,
        ScreenFilters,
        format_screen_table,
        list_universes,
        resolve_universe,
        save_screen,
    )

    if list_only or not universe:
        click.echo("\n  Built-in universes:")
        for name, description in list_universes().items():
            click.echo(f"    {name:<12} {description}")
        click.echo("\n  Or pass a ticker file path and/or literal tickers.\n")
        if not list_only:
            raise click.UsageError("Specify at least one UNIVERSE.")
        return

    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]

    try:
        resolved = resolve_universe(list(universe), data_dir=output_dir, use_cache=use_cache)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not resolved.tickers:
        raise click.ClickException("Universe is empty.")

    click.echo("=" * 70)
    click.echo(f"  Screening {len(resolved.tickers)} tickers ({resolved.label})")
    click.echo("=" * 70)

    screener = Screener(
        fetcher=DataFetcher(cache_dir=output_dir),
        options=AnalysisOptions(
            period=ctx.obj["period"],
            use_cache=use_cache,
            scoring_config=get_scoring_config(config_name),
        ),
        workers=workers,
    )
    filters = ScreenFilters(
        sectors=tuple(sectors),
        exclude_sectors=tuple(exclude_sectors),
        min_market_cap=min_mcap,
        max_market_cap=max_mcap,
        min_avg_volume=min_volume,
        currency=currency,
    )

    stage_labels = {"rank": "  Ranking universe  ", "score": "  Scoring shortlist "}
    bars = {}

    def _progress(stage: str, done: int, total: int):
        if stage not in bars:
            bars[stage] = click.progressbar(length=total, label=stage_labels[stage])
            bars[stage].__enter__()
        bars[stage].update(1)
        if done == total:
            bars[stage].__exit__(None, None, None)

    result = screener.run(
        resolved.tickers,
        filters=filters,
        top_n=top,
        universe_label=resolved.label,
        progress=_progress,
    )

    click.echo()
    click.echo(format_screen_table(result))

    filtered = sum(1 for r in result.excluded.values() if r.startswith("filtered"))
    unavailable = len(result.excluded) - filtered
    if result.cap_currency:
        click.echo(f"\n  Market caps compared in {result.cap_currency}")
    if filtered or unavailable:
        click.echo(f"\n  Excluded: {filtered} by filters, {unavailable} with no usable data")
        if unavailable:
            sample = [t for t, r in result.excluded.items() if not r.startswith("filtered")][:8]
            click.echo(f"    no data: {', '.join(sample)}{' ...' if unavailable > 8 else ''}")

    from ..tracking import DEFAULT_WATCHLIST, add_to_watchlist, history_row, load_watchlist

    record_history(
        output_dir,
        [history_row(c.report, c.scoring, "screen") for c in result.scored if c.report],
    )

    if save:
        for path in save_screen(result, output_dir, ctx.obj["output_format"]):
            click.echo(f"  Saved: {path}")

    if add_top:
        watchlist_path = Path(DEFAULT_WATCHLIST)
        listed = load_watchlist(watchlist_path)
        best = [c for c in result.scored if c.scoring][:add_top]
        new = [c for c in best if c.ticker not in listed]  # keep existing theses
        for c in new:
            thesis = (
                f"screen {resolved.label} ({config_name}): "
                f"{c.scoring.composite_score:.0f} {c.scoring.signal}"
            )
            add_to_watchlist(watchlist_path, [c.ticker], thesis=thesis)
        already = len(best) - len(new)
        click.echo(
            f"  Watchlist: added {', '.join(c.ticker for c in new) or 'nothing'}"
            + (f" ({already} already listed)" if already else "")
        )

    if result.scored:
        best = [c.ticker for c in result.scored[:3] if c.scoring]
        if best:
            click.echo(f"\n  Next: quant report {best[0]}   |   quant compare {' '.join(best)}")
    click.echo()


@click.command()
@click.option(
    "--min-overlap",
    default=2,
    type=int,
    help="Minimum portfolios a ticker must appear in (default: 2).",
)
@click.option(
    "--top",
    default=20,
    type=int,
    help="Number of top signals to display (default: 20).",
)
@click.option(
    "--sector",
    default=None,
    type=str,
    help="Filter results to a specific sector (e.g., 'Technology').",
)
@click.option(
    "--enrich/--no-enrich",
    default=False,
    help="Enrich holdings with sector/industry data from yfinance (slow).",
)
@click.option(
    "--list-sources",
    is_flag=True,
    default=False,
    help="List available portfolio sources and configured filers.",
)
@click.pass_context
def discover(ctx, min_overlap, top, sector, enrich, list_sources):
    """Discover investment signals from notable portfolios.

    Analyzes institutional 13F filings (Berkshire Hathaway, ARK, Soros, etc.)
    for cross-portfolio patterns: ticker overlap, sector clustering,
    activity convergence, and contrarian signals.

    Examples:
      quant discover                    # Show all cross-portfolio signals
      quant discover --min-overlap 3    # Tickers in 3+ portfolios
      quant discover --sector Technology  # Filter by sector
      quant discover --enrich           # Add sector/industry data (slower)
      quant discover --list-sources     # Show configured portfolio sources
    """
    from ..discovery import PortfolioAnalyzer, render_text
    from ..discovery.sources import Edgar13FSource

    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
    output_format = ctx.obj["output_format"]

    source = Edgar13FSource(cache_dir=output_dir)

    if list_sources:
        click.echo("\n  Available portfolio sources:")
        click.echo("  " + "-" * 50)
        for filer in source.list_available():
            click.echo(f"  {filer['name']:<30} CIK: {filer['id']}")
            if filer.get("description"):
                click.echo(f"    {filer['description']}")
        click.echo()
        return

    click.echo("=" * 70)
    click.echo("  PORTFOLIO DISCOVERY")
    click.echo("=" * 70)
    click.echo("\n  Fetching notable portfolios from SEC EDGAR 13F filings...")

    portfolios = source.fetch_portfolios(use_cache=use_cache)

    if not portfolios:
        click.echo("  No portfolios fetched. Check your internet connection.")
        return

    click.echo(f"  Loaded {len(portfolios)} portfolios")

    # Show action stats from filing diff
    actions = {}
    for p in portfolios:
        for h in p.holdings:
            if h.action:
                actions[h.action] = actions.get(h.action, 0) + 1
    if actions:
        action_str = ", ".join(f"{k}: {v}" for k, v in sorted(actions.items()))
        click.echo(f"  Actions inferred from quarter-over-quarter diff: {action_str}")

    # Enrichment: either full (--enrich) or auto (top overlap tickers only)
    from ..discovery.enrichment import HoldingEnricher

    enricher = HoldingEnricher(cache_dir=output_dir)

    if enrich:
        click.echo("  Enriching ALL holdings with sector/industry data (slow)...")
        for portfolio in portfolios:
            enricher.enrich_portfolio(portfolio)
    else:
        # Auto-enrich: run overlap detection first, then enrich only top tickers
        analyzer_pre = PortfolioAnalyzer(min_overlap=min_overlap)
        pre_signals = analyzer_pre.detect_overlap(portfolios)
        top_tickers = {s.ticker for s in pre_signals[: top * 2]}  # Enrich a bit more than displayed
        if top_tickers:
            click.echo(
                f"  Auto-enriching top {len(top_tickers)} overlap tickers with sector data..."
            )
            enricher.enrich_tickers_in_portfolios(portfolios, top_tickers)

    # Run analysis
    analyzer = PortfolioAnalyzer(min_overlap=min_overlap)
    result = analyzer.analyze(portfolios)

    # Apply sector filter
    if sector:
        sector_lower = sector.lower()
        result.overlap_signals = [
            s for s in result.overlap_signals if s.sector and sector_lower in s.sector.lower()
        ]
        result.sector_clusters = [
            c for c in result.sector_clusters if sector_lower in c.sector.lower()
        ]

    click.echo(render_text(result, top=top))

    # Save output if requested
    if output_format in ("json", "all"):
        import json as _json

        out_path = Path(output_dir) / "_discovery" / "discovery_result.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        click.echo(f"  Results saved to: {out_path}")

    if output_format in ("toon", "all"):
        try:
            import toon

            out_path = Path(output_dir) / "_discovery" / "discovery_result.toon"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(toon.encode(result.to_dict()), encoding="utf-8")
            click.echo(f"  TOON output:  {out_path}")
        except ImportError:
            pass

    if result.overlap_signals and output_format in ("json", "all"):
        click.echo("\n  Next: quant screen discover   (factor-rank and score these picks)")
    click.echo()
