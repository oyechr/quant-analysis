"""The Python API example runs end to end (on the fake market), so it can't silently rot."""

import runpy
import sys
from pathlib import Path

from conftest import make_context, make_statements

EXAMPLE = Path(__file__).parent.parent / "examples" / "python_api.py"


def test_python_api_example_runs(fake_market, monkeypatch, tmp_path, capsys):
    for symbol in ("AAPL", "MSFT", "GOOGL", "NVDA", "JNJ"):
        fake_market.attribute_overrides[symbol] = {**make_statements(), **make_context(symbol)}
    monkeypatch.chdir(tmp_path)  # the example caches under ./data
    monkeypatch.setattr(sys, "argv", ["python_api.py", "AAPL"])

    runpy.run_path(str(EXAMPLE), run_name="__main__")

    out = capsys.readouterr().out
    assert "STOCK SCORE: AAPL" in out
    assert "VET: AAPL" in out
    assert "SCREEN: custom" in out
    assert "Best by composite score:" in out
