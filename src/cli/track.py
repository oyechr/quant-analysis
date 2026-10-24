"""Tracking picks over time: watchlist, changes."""

from pathlib import Path

import click

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from .common import (
    config_option,
    get_scoring_config,
    workers_option,
)


def _watchlist_file_option():
    from ..tracking import DEFAULT_WATCHLIST

    return click.option(
        "--file",
        "watchlist_file",
        default=DEFAULT_WATCHLIST,
        show_default=True,
        type=click.Path(dir_okay=False, path_type=Path),
        help="Watchlist file.",
    )


@click.group()
@_watchlist_file_option()
@click.pass_context
def watchlist(ctx, watchlist_file):
    """Keep a list of tickers to follow, with a thesis and price levels.

    The list lives in watchlist.toml (gitignored; edit it by hand if you
    like). `quant changes` checks it, and `quant screen watchlist` screens it.

    \b
    Examples:
      quant watchlist add EQNR.OL --thesis "Cheap vs peers" --target 450 --stop 380
      quant watchlist add AAPL MSFT
      quant watchlist rm MSFT
      quant watchlist ls
    """
    ctx.obj["watchlist_file"] = watchlist_file


@watchlist.command("add")
@click.argument("tickers", nargs=-1, required=True)
@click.option("--thesis", default=None, help="One line on why you're watching it.")
@click.option("--target", type=float, default=None, help="Target price (listing currency).")
@click.option("--stop", type=float, default=None, help="Stop price (listing currency).")
@click.pass_context
def watchlist_add(ctx, tickers, thesis, target, stop):
    """Add TICKERS, or update the thesis/target/stop of ones already listed."""
    from ..tracking import add_to_watchlist

    path = ctx.obj["watchlist_file"]
    try:
        added, updated = add_to_watchlist(path, tickers, thesis=thesis, target=target, stop=stop)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if added:
        click.echo(f"  Added {', '.join(added)} to {path}")
    if updated:
        click.echo(f"  Updated {', '.join(updated)}")


@watchlist.command("rm")
@click.argument("tickers", nargs=-1, required=True)
@click.pass_context
def watchlist_rm(ctx, tickers):
    """Remove TICKERS from the watchlist."""
    from ..tracking import remove_from_watchlist

    path = ctx.obj["watchlist_file"]
    try:
        removed, missing = remove_from_watchlist(path, tickers)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if removed:
        click.echo(f"  Removed {', '.join(removed)} from {path}")
    if missing:
        click.echo(f"  Not on the watchlist: {', '.join(missing)}")


@watchlist.command("ls")
@click.pass_context
def watchlist_ls(ctx):
    """List the watchlist with each ticker's last recorded score."""
    from ..tracking import load_history, load_watchlist, render_watchlist

    path = ctx.obj["watchlist_file"]
    try:
        items = load_watchlist(path)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not items:
        click.echo(f"  {path} is empty. Add tickers with: quant watchlist add T --thesis '...'")
        return

    last = {row["ticker"]: row for row in load_history(ctx.obj["output_dir"])}
    click.echo(render_watchlist(path, items, last))


@click.command()
@click.argument("tickers", nargs=-1)
@config_option()
@workers_option()
@_watchlist_file_option()
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
@click.pass_context
def changes(ctx, tickers, config_name, workers, watchlist_file, as_json):
    """What moved since the last run, for the watchlist or TICKERS.

    Rescores each ticker, records it in the score history
    (<output-dir>/_history/scores.csv), and compares it with its latest run
    from an earlier day: score and signal, red flags that appeared or
    cleared, the price move, price against the watchlist target/stop, and
    earnings in the next 14 days. Every report/score/vet/screen run also
    feeds the history.

    \b
    Examples:
      quant changes
      quant changes EQNR.OL AAPL
      quant changes --config value
    """
    import json as _json

    from ..tracking import load_watchlist, render_text, track_changes

    output_dir = ctx.obj["output_dir"]
    try:
        watched = load_watchlist(watchlist_file)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    tickers_list = [t.upper() for t in tickers] or list(watched)
    if not tickers_list:
        raise click.ClickException(
            f"No tickers given and {watchlist_file} is empty. "
            "Add some with: quant watchlist add T --thesis '...'"
        )

    def progress(ticker, error):
        if not as_json:
            mark = "✗" if error else "✓"
            click.echo(f"  {mark} {ticker}" + (f": {error}" if error else ""), err=True)

    if not as_json:
        click.echo(f"  Checking {len(tickers_list)} ticker(s)...", err=True)
    result = track_changes(
        tickers_list,
        fetcher=DataFetcher(cache_dir=output_dir),
        options=AnalysisOptions(
            period=ctx.obj["period"],
            use_cache=ctx.obj["use_cache"],
            include_context=False,
            scoring_config=get_scoring_config(config_name),
        ),
        watchlist=watched,
        data_dir=output_dir,
        workers=workers,
        progress=progress,
    )
    data = result.to_dict()
    if as_json:
        click.echo(_json.dumps(data, indent=2, default=str))
    else:
        click.echo(render_text(data))
