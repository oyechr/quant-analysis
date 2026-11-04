"""
Tracking: a watchlist, a score history, what changed since the last run, and
a decision journal.
"""

from .changes import (
    ChangesResult,
    TickerChange,
    render_markdown,
    render_text,
    summary_line,
    track_changes,
)
from .history import (
    HISTORY_COLUMNS,
    flag_titles,
    history_path,
    history_row,
    load_history,
    record_scores,
)
from .journal import (
    DEFAULT_JOURNAL,
    OPENING,
    Decision,
    Outcome,
    ThesisCheck,
    add_decision,
    check_journal,
    check_thesis,
    load_journal,
    look_back,
    render_journal,
    render_look_back,
    save_journal,
    snapshot_row,
    summarize_outcomes,
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
    "DEFAULT_JOURNAL",
    "DEFAULT_WATCHLIST",
    "HISTORY_COLUMNS",
    "OPENING",
    "ChangesResult",
    "Decision",
    "Outcome",
    "ThesisCheck",
    "TickerChange",
    "WatchItem",
    "add_decision",
    "add_to_watchlist",
    "check_journal",
    "check_thesis",
    "flag_titles",
    "history_path",
    "history_row",
    "load_history",
    "load_journal",
    "load_watchlist",
    "look_back",
    "record_scores",
    "remove_from_watchlist",
    "render_journal",
    "render_look_back",
    "render_markdown",
    "render_text",
    "render_watchlist",
    "save_journal",
    "save_watchlist",
    "snapshot_row",
    "summarize_outcomes",
    "summary_line",
    "track_changes",
]
