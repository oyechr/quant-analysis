"""
Screening: find candidates across an index or ticker list.

Two stages: a cheap multi-factor ranking of the whole universe, then the full
analysis pipeline for the top-ranked names.
"""

from .screener import (
    ScreenCandidate,
    Screener,
    ScreenFilters,
    ScreenResult,
    format_screen_table,
    parse_amount,
    save_screen,
)
from .universe import BUILTIN_INDEXES, Universe, list_universes, resolve_universe

__all__ = [
    "BUILTIN_INDEXES",
    "ScreenCandidate",
    "ScreenFilters",
    "ScreenResult",
    "Screener",
    "Universe",
    "format_screen_table",
    "list_universes",
    "parse_amount",
    "resolve_universe",
    "save_screen",
]
