"""
TOON Serialization Utilities
Converts report data to Token-Oriented Object Notation (TOON) format,
a compact, human-readable encoding optimized for LLM input.

TOON provides a lossless representation of JSON data that minimizes tokens
and makes structure easy for models to follow. It uses YAML-style indentation
for objects and CSV-like tabular format for uniform arrays.

See: https://github.com/toon-format/spec
"""

import json
import logging
from typing import Any, Dict

from toon import encode as toon_encode

from .serialization import clean_for_json

logger = logging.getLogger(__name__)


def report_to_toon(data: Dict[str, Any]) -> str:
    """
    Convert report data dictionary to TOON format string.

    Accepts the same Dict[str, Any] that _save_json_report receives.
    Pre-cleans the data (NaN → None, Timestamps → strings) via clean_for_json,
    then encodes to TOON.

    Args:
        data: Report data dictionary (as produced by generate_full_report)

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

    return toon_encode(json_safe)
