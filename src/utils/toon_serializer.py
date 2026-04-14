"""
TOON Serialization Utilities
Converts report data to Token-Oriented Object Notation (TOON) format,
a compact, human-readable encoding optimized for LLM input.

TOON provides a lossless representation of JSON data that minimizes tokens
and makes structure easy for models to follow. It uses YAML-style indentation
for objects and CSV-like tabular format for uniform arrays.

Sections with deeply nested, non-uniform structures (e.g., news articles with
9 levels of nesting) are excluded from TOON encoding because they produce
larger output than compact JSON. These sections are omitted from the TOON
output — the full data remains available in the JSON report.

See: https://github.com/toon-format/spec
"""

import json
import logging
from typing import Any, Dict, Sequence

from toon import encode as toon_encode

from .serialization import clean_for_json

logger = logging.getLogger(__name__)

# Sections excluded from TOON encoding because their deeply nested,
# non-uniform structures produce larger output than compact JSON.
# The news section in particular has 9 levels of nesting and adds ~17%
# overhead vs compact JSON. These sections remain in the JSON report.
TOON_EXCLUDED_SECTIONS: Sequence[str] = ("news",)


def report_to_toon(
    data: Dict[str, Any],
    excluded_sections: Sequence[str] = TOON_EXCLUDED_SECTIONS,
) -> str:
    """
    Convert report data dictionary to TOON format string.

    Accepts the same Dict[str, Any] that _save_json_report receives.
    Pre-cleans the data (NaN → None, Timestamps → strings) via clean_for_json,
    then encodes to TOON.

    Sections listed in ``excluded_sections`` are omitted from the TOON output
    because their deeply nested structures are larger in TOON than compact JSON.

    Args:
        data: Report data dictionary (as produced by generate_full_report)
        excluded_sections: Top-level keys to omit from TOON output.
            Defaults to TOON_EXCLUDED_SECTIONS (currently: ``("news",)``).

    Returns:
        TOON-formatted string

    Raises:
        TypeError: If data cannot be serialized
    """
    # Pre-clean: handle NaN, Timestamps, DataFrames, etc.
    cleaned = clean_for_json(data)

    # json.loads(json.dumps(...)) ensures all values are pure JSON-compatible types
    # (e.g., numpy int64 → int, custom objects → str via default=str)
    json_safe = json.loads(json.dumps(cleaned, default=str))

    # Remove sections unsuitable for TOON (deeply nested / non-uniform)
    if excluded_sections:
        excluded = set(excluded_sections)
        json_safe = {k: v for k, v in json_safe.items() if k not in excluded}

    return toon_encode(json_safe)
