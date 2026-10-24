"""Signal backtests: backtest."""

import sys

import click

from ..data_fetcher import DataFetcher
from .common import (
    config_option,
    get_scoring_config,
    workers_option,
)


def _parse_horizons(ctx, param, value):
    try:
        horizons = sorted({int(h) for h in value.split(",") if h.strip()})
    except ValueError as e:
        raise click.BadParameter("use whole months, e.g. 1,3,6") from e
    if not horizons or horizons[0] < 1 or horizons[-1] > 24:
        raise click.BadParameter("use months between 1 and 24, e.g. 1,3,6")
    return horizons


@click.command()
@click.argument("universe", nargs=-1, required=True)
@click.option(
    "--years", default=5, show_default=True, type=click.IntRange(1, 15), help="Years to test."
)
@click.option(
    "--horizons",
    default="1,3,6",
    show_default=True,
    callback=_parse_horizons,
    help="Forward return horizons in months.",
)
@config_option()
@workers_option()
@click.option("--json", "as_json", is_flag=True, help="Print the summary as JSON.")
@click.option("--save/--no-save", default=True, show_default=True, help="Write results files.")
@click.pass_context
def backtest(ctx, universe, years, horizons, config_name, workers, as_json, save):
    """How well did the price-based signals predict the next months?

    Walks through every month-end of the last --years years. At each one, it
    scores every ticker using only the prices up to that day: the technical
    and risk dimensions, the composite of the two (with the preset's
    Buy/Hold/Sell bands), 12-1 momentum, and low volatility. It then measures
    the returns over the next --horizons months against each ticker's home
    benchmark.

    Reports the rank IC, the top-minus-bottom quintile spread, the hit rate,
    and the returns per signal band, with 95% intervals. Fundamental and
    valuation scores can't be tested this way: Yahoo's statements are
    restated and undated.

    UNIVERSE works as in `screen` (sp100, obx, watchlist, a file, tickers).
    The first run downloads up to 10 years of prices per ticker.

    \b
    Examples:
      quant backtest sp100
      quant backtest obx --years 3 --horizons 1,3
      quant backtest sp100 --config growth --no-save
    """
    import json as _json

    from ..backtest import backtest_to_dict, render_text, run_backtest, save_backtest
    from ..screening import resolve_universe

    output_dir = ctx.obj["output_dir"]
    use_cache = ctx.obj["use_cache"]
    try:
        resolved = resolve_universe(list(universe), data_dir=output_dir, use_cache=use_cache)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not resolved.tickers:
        raise click.ClickException("Universe is empty.")

    bar = None
    if not as_json:
        click.echo(f"  Backtesting {len(resolved.tickers)} tickers over {years} years...", err=True)
        bar = click.progressbar(length=len(resolved.tickers), label="  Tickers", file=sys.stderr)
        bar.__enter__()

    result = run_backtest(
        resolved.tickers,
        fetcher=DataFetcher(cache_dir=output_dir),
        years=years,
        horizons=horizons,
        config=get_scoring_config(config_name),
        use_cache=use_cache,
        workers=workers,
        universe_label=resolved.label,
        progress=lambda ticker, error: bar.update(1) if bar else None,
    )
    if bar:
        bar.__exit__(None, None, None)

    data = backtest_to_dict(result)
    if as_json:
        click.echo(_json.dumps(data, indent=2, default=str))
    else:
        click.echo(render_text(data))
    if save:
        for path in save_backtest(result, data, output_dir):
            click.echo(f"  Saved: {path}", err=True)
