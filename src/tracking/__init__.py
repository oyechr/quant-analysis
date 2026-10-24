"""
Tracking: a watchlist, a score history, and what changed since the last run.
"""

from .changes import ChangesResult, TickerChange, render_text, track_changes
from .history import (
    HISTORY_COLUMNS,
    flag_titles,
    history_path,
    history_row,
    load_history,
    record_scores,
)
from .watchlist import (
    DEFAULT_WATCHLIST,
    WatchItem,
    add_to_watchlist,
    load_watchlist,
    remove_from_watchlist,
    render_watchlist,
    save_watchlist,
)

__all__ = [
    "DEFAULT_WATCHLIST",
    "HISTORY_COLUMNS",
    "ChangesResult",
    "TickerChange",
    "WatchItem",
    "add_to_watchlist",
    "flag_titles",
    "history_path",
    "history_row",
    "load_history",
    "load_watchlist",
    "record_scores",
    "remove_from_watchlist",
    "render_text",
    "render_watchlist",
    "save_watchlist",
    "track_changes",
]
