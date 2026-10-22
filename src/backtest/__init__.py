"""
Backtest: how well the price-based signals predicted the following months.
"""

from .engine import (
    DEFAULT_HORIZONS,
    SIGNALS,
    BacktestResult,
    backtest_months,
    history_period,
    run_backtest,
)
from .render import backtest_to_dict, render_markdown, render_text, save_backtest
from .stats import band_table, mean_ci, monthly_ic, monthly_spread, newey_west_se, summarize

__all__ = [
    "DEFAULT_HORIZONS",
    "SIGNALS",
    "BacktestResult",
    "backtest_months",
    "backtest_to_dict",
    "band_table",
    "history_period",
    "mean_ci",
    "monthly_ic",
    "monthly_spread",
    "newey_west_se",
    "render_markdown",
    "render_text",
    "run_backtest",
    "save_backtest",
    "summarize",
]
