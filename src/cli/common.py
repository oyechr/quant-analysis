"""Options and helpers shared by the command modules."""

import logging
import sys

import click

from ..scoring import ScoringConfig
from ..utils.concurrency import DEFAULT_WORKERS

PRESETS = ["default", "value", "growth", "income"]


def configure_logging(verbose: bool, quiet: bool):
    """Set up logging based on verbosity flags."""
    # Ensure UTF-8 output on Windows where the default console encoding (cp1252)
    # cannot represent the Unicode block characters used in scorecards.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    # Progress goes through click.echo; library logging is for problems (default)
    # or diagnostics (-v).
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", force=True)
    # yfinance logs its own ERRORs for delisted/unknown symbols; our commands already
    # report those per ticker, so only show them when debugging.
    logging.getLogger("yfinance").setLevel(logging.DEBUG if verbose else logging.CRITICAL)


def get_scoring_config(config_name: str) -> ScoringConfig:
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


def config_option(help_text: str = "Scoring preset (default, value, growth, income)."):
    return click.option(
        "--config",
        "config_name",
        type=click.Choice(PRESETS, case_sensitive=False),
        default="default",
        help=help_text,
    )


def workers_option():
    return click.option(
        "--workers",
        default=DEFAULT_WORKERS,
        type=click.IntRange(1, 16),
        show_default=True,
        help="Tickers analyzed in parallel (keep modest; Yahoo rate-limits).",
    )


def echo_freshness_warnings(ticker: str, report_data: dict):
    """Surface stale/expired data so scores aren't trusted blindly."""
    for warning in (report_data.get("data_freshness") or {}).get("warnings", []):
        click.echo(f"  ! {ticker}: {warning}", err=True)


def record_history(output_dir: str, rows: list):
    """Append scored runs to the score history; a write failure only warns."""
    from ..tracking import record_scores

    try:
        record_scores(rows, output_dir)
    except OSError as e:
        click.echo(f"  ! Score history not updated: {e}", err=True)
