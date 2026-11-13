"""Options and helpers shared by the command modules."""

import json
import logging
import math
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

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


class FiniteFloat(click.ParamType):
    """A float that isn't inf or nan (click.FLOAT accepts both), optionally >= min."""

    name = "float"

    def __init__(self, min: float | None = None) -> None:
        self.min = min

    def convert(self, value, param, ctx):
        number = click.FLOAT.convert(value, param, ctx)
        if not math.isfinite(number):
            self.fail(f"{value!r} is not a usable number", param, ctx)
        if self.min is not None and number < self.min:
            self.fail(f"{value!r} is below {self.min:g}", param, ctx)
        return number


FINITE_FLOAT = FiniteFloat()
NON_NEGATIVE_FLOAT = FiniteFloat(min=0)
POSITIVE_INT = click.IntRange(min=1)


def to_json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def echo_status(message: str = "") -> None:
    """Progress and status lines go to stderr, so stdout stays the result."""
    click.echo(message, err=True)


def echo_progress(ticker: str, error: Exception | str | None) -> None:
    """One ✓/✗ line per ticker, on stderr."""
    mark = "✗" if error else "✓"
    echo_status(f"  {mark} {ticker}" + (f": {error}" if error else ""))


def echo_banner(title: str) -> None:
    echo_status("=" * 70)
    echo_status(f"  {title}")
    echo_status("=" * 70)


@contextmanager
def stage_progress(labels: dict[str, str]) -> Iterator[Callable[[str, int, int], None]]:
    """
    A progress callback (stage, done, total) drawing one bar per stage on
    stderr. Each bar closes when its stage completes, and on the way out if
    the run fails first.
    """
    bars: dict[str, Any] = {}

    def update(stage: str, done: int, total: int) -> None:
        if stage not in bars:
            bars[stage] = click.progressbar(
                length=total, label=labels.get(stage, stage), file=sys.stderr
            )
            bars[stage].__enter__()
        bars[stage].update(1)
        if done == total:
            bars.pop(stage).__exit__(None, None, None)

    try:
        yield update
    finally:
        for bar in bars.values():
            bar.__exit__(None, None, None)


def has_score(report: dict[str, Any], scoring: Any) -> bool:
    """
    A usable score: something was scored and there's a price. An unknown
    symbol still gets a meaningless 50/100 Hold at 0% confidence.
    """
    from ..vetting.verdict import current_price

    return scoring is not None and current_price(report) is not None


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
