"""
Tests for TOON serialization of financial reports.

Validates that report data can be losslessly converted to TOON format
and round-tripped back to equivalent Python data structures.

The news section is excluded from TOON output by default because its
deeply nested structure (9 levels) is larger in TOON than compact JSON.
"""

import json
import math
from pathlib import Path

import pytest
from toon import DecodeOptions
from toon import decode as toon_decode

from src.utils.toon_serializer import TOON_EXCLUDED_SECTIONS, report_to_toon

# Path to sample report data
SAMPLE_REPORTS_DIR = Path(__file__).parent.parent / "data"


def _load_sample_report(ticker: str = "AAPL") -> dict:
    """Load a sample full_report.json for testing."""
    report_path = SAMPLE_REPORTS_DIR / ticker / "reports" / "full_report.json"
    if not report_path.exists():
        pytest.skip(f"Sample report not found: {report_path}")
    with open(report_path) as f:
        return json.load(f)


def _values_equal(a, b, float_tolerance: float = 1e-9) -> bool:
    """
    Recursively compare two values for equality, with float tolerance.
    TOON may decode integers as floats in some edge cases, so we also
    compare int-to-float when the float has no fractional part.
    """
    if a is None and b is None:
        return True
    if type(a) != type(b):
        # Allow int/float comparison
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) < float_tolerance
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_values_equal(a[k], b[k], float_tolerance) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_values_equal(x, y, float_tolerance) for x, y in zip(a, b))
    if isinstance(a, float):
        if math.isnan(a) and math.isnan(b):
            return True
        return abs(a - b) < float_tolerance
    return a == b


class TestReportToToon:
    """Test the report_to_toon conversion function."""

    def test_encode_returns_string(self):
        """report_to_toon should return a non-empty string."""
        data = {"ticker": "TEST", "value": 42}
        result = report_to_toon(data)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_encode_simple_object(self):
        """Simple key-value objects should encode correctly."""
        data = {"name": "Apple", "price": 150.25, "active": True}
        result = report_to_toon(data)
        assert "name: Apple" in result
        assert "price: 150.25" in result
        assert "active: true" in result

    def test_encode_nested_object(self):
        """Nested objects should use indentation."""
        data = {"info": {"symbol": "AAPL", "sector": "Technology"}}
        result = report_to_toon(data)
        assert "info:" in result
        assert "symbol: AAPL" in result
        assert "sector: Technology" in result

    def test_encode_uniform_array(self):
        """Uniform arrays of objects should use tabular format."""
        data = {
            "items": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Charlie"},
            ]
        }
        result = report_to_toon(data)
        # TOON tabular format: items[3,]{id,name}:
        assert "items[3" in result
        assert "id" in result
        assert "name" in result

    def test_encode_null_values(self):
        """None values should encode as null."""
        data = {"value": None, "nested": {"also_null": None}}
        result = report_to_toon(data)
        assert "null" in result

    def test_encode_empty_dict(self):
        """Empty dict should encode without error."""
        result = report_to_toon({})
        assert isinstance(result, str)

    def test_encode_empty_list_value(self):
        """Dict with empty list value should encode without error."""
        data = {"items": []}
        result = report_to_toon(data)
        assert isinstance(result, str)

    def test_nan_values_cleaned(self):
        """NaN floats should be cleaned to null before encoding."""
        data = {"value": float("nan")}
        result = report_to_toon(data)
        assert "null" in result
        assert "nan" not in result.lower()

    def test_roundtrip_simple(self):
        """Simple data should roundtrip through TOON encode/decode."""
        data = {
            "ticker": "TEST",
            "price": 100.5,
            "active": True,
            "notes": None,
        }
        toon_str = report_to_toon(data)
        decoded = toon_decode(toon_str)
        assert _values_equal(data, decoded)

    def test_roundtrip_with_arrays(self):
        """Data with uniform arrays should roundtrip."""
        data = {
            "earnings": [
                {"quarter": "Q1", "eps": 1.5, "surprise": 5.0},
                {"quarter": "Q2", "eps": 1.7, "surprise": 3.2},
            ]
        }
        toon_str = report_to_toon(data)
        decoded = toon_decode(toon_str)
        assert _values_equal(data, decoded)


class TestFullReportToon:
    """Test TOON conversion with actual full report data."""

    def test_encode_full_report(self):
        """Full report should encode to TOON without errors."""
        data = _load_sample_report()
        result = report_to_toon(data)
        assert isinstance(result, str)
        assert len(result) > 100  # Should produce substantial output

    def test_full_report_contains_key_sections(self):
        """TOON output should contain all major report sections (except excluded ones)."""
        data = _load_sample_report()
        result = report_to_toon(data)

        expected_keys = ["ticker", "info", "price_data", "technical_analysis"]
        for key in expected_keys:
            assert key in result, f"Missing key '{key}' in TOON output"

    def test_full_report_excludes_news(self):
        """News section should be excluded from TOON output by default."""
        data = _load_sample_report()
        result = report_to_toon(data)
        # The top-level "news:" key should not appear
        lines = result.split("\n")
        top_level_keys = [line.rstrip(":") for line in lines if line and not line.startswith(" ")]
        assert "news" not in top_level_keys, "news section should be excluded from TOON"

    def test_full_report_includes_news_when_not_excluded(self):
        """News section should be included when excluded_sections is empty."""
        data = _load_sample_report()
        result = report_to_toon(data, excluded_sections=())
        assert "news:" in result

    def test_news_exclusion_reduces_toon_size(self):
        """Excluding news should make TOON smaller than compact JSON (sans news)."""
        data = _load_sample_report()
        toon_default = report_to_toon(data)
        toon_with_news = report_to_toon(data, excluded_sections=())
        # Default (no news) should be smaller
        assert len(toon_default) < len(toon_with_news)

    def test_toon_default_is_smaller_than_compact_json_without_news(self):
        """TOON (excluding news) should be smaller than compact JSON of the same sections."""
        data = _load_sample_report()
        toon_str = report_to_toon(data)
        # Build equivalent compact JSON without excluded sections
        data_no_excluded = {k: v for k, v in data.items() if k not in TOON_EXCLUDED_SECTIONS}
        compact_json = json.dumps(data_no_excluded, separators=(",", ":"), default=str)
        assert len(toon_str) < len(
            compact_json
        ), f"TOON ({len(toon_str)}) should be smaller than compact JSON ({len(compact_json)})"

    def test_full_report_roundtrip(self):
        """Full report (sans excluded sections) should roundtrip through TOON."""
        data = _load_sample_report()
        toon_str = report_to_toon(data)
        decoded = toon_decode(toon_str, DecodeOptions(strict=False))

        assert isinstance(decoded, dict)
        expected_keys = {k for k in data.keys() if k not in TOON_EXCLUDED_SECTIONS}
        assert set(decoded.keys()) == expected_keys
        assert decoded["ticker"] == data["ticker"]

    def test_full_report_preserves_numeric_values(self):
        """Key numeric values should survive TOON roundtrip."""
        data = _load_sample_report()
        toon_str = report_to_toon(data)
        decoded = toon_decode(toon_str, DecodeOptions(strict=False))

        # Check a few specific numeric values survive
        if data.get("info"):
            original_pe = data["info"].get("pe_ratio")
            decoded_pe = decoded["info"].get("pe_ratio")
            if original_pe is not None:
                assert abs(float(original_pe) - float(decoded_pe)) < 0.01

    def test_toon_is_more_compact_than_pretty_json(self):
        """TOON should be smaller than pretty-printed JSON (of same sections)."""
        data = _load_sample_report()
        toon_str = report_to_toon(data)
        data_no_excluded = {k: v for k, v in data.items() if k not in TOON_EXCLUDED_SECTIONS}
        pretty_json = json.dumps(data_no_excluded, indent=2, default=str)
        assert len(toon_str) < len(pretty_json)


class TestEdgeCases:
    """Test edge cases for TOON serialization."""

    def test_deeply_nested_structure(self):
        """Deeply nested structures should encode without error."""
        data = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        result = report_to_toon(data)
        assert "deep" in result

    def test_mixed_type_array(self):
        """Arrays with mixed types should encode as list items."""
        data = {"items": [1, "two", True, None]}
        result = report_to_toon(data)
        assert isinstance(result, str)

    def test_string_with_special_characters(self):
        """Strings with special characters should be properly quoted."""
        data = {"url": "https://example.com/path?q=1&b=2"}
        result = report_to_toon(data)
        assert "https://example.com" in result

    def test_large_numbers(self):
        """Large numbers (market cap) should encode correctly."""
        data = {"market_cap": 3816067170304}
        result = report_to_toon(data)
        assert "3816067170304" in result

    def test_boolean_values(self):
        """Booleans should encode as true/false (lowercase)."""
        data = {"is_active": True, "is_deleted": False}
        result = report_to_toon(data)
        assert "true" in result
        assert "false" in result

    def test_empty_string_value(self):
        """Empty strings should be properly quoted."""
        data = {"name": ""}
        result = report_to_toon(data)
        assert isinstance(result, str)

    def test_section_with_none_value(self):
        """Report sections that are None should encode as null."""
        data = {
            "ticker": "TEST",
            "technical_analysis": None,
            "fundamental_analysis": {"ticker": "TEST", "analysis": {}},
        }
        result = report_to_toon(data)
        assert "null" in result
        assert "ticker: TEST" in result
