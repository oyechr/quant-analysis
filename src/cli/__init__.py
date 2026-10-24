"""
CLI Interface for Quantitative Analysis Tool

Provides subcommands: report, score, screen, vet, compare, chat, discover, watch,
import-portfolio, review, watchlist, changes, backtest
Install with: pip install -e .
Usage: quant report AAPL

Each module holds one command group; this module defines the `quant` group and
registers them.
"""

import click

from . import analyze, backtest, chat, find, portfolio, track
from .common import configure_logging


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
    configure_logging(verbose, quiet)
    ctx.ensure_object(dict)
    ctx.obj["output_dir"] = output_dir
    ctx.obj["use_cache"] = not no_cache
    ctx.obj["output_format"] = output_format
    ctx.obj["period"] = period


COMMANDS = (
    analyze.report,
    analyze.score,
    analyze.vet,
    analyze.compare,
    analyze.watch,
    find.screen,
    find.discover,
    chat.chat,
    portfolio.import_portfolio,
    portfolio.review,
    portfolio.rebalance,
    track.watchlist,
    track.changes,
    backtest.backtest,
)
for _command in COMMANDS:
    cli.add_command(_command)
