"""
Tests for the technical trend state (src/analysis/technical.py). Prices are
synthetic.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.technical import TechnicalAnalyzer


def _analyzer(**columns):
    """An analyzer whose frame holds the given indicator columns (last values last)."""
    n = len(next(iter(columns.values())))
    index = pd.bdate_range("2026-01-05", periods=n)
    prices = pd.DataFrame(
        {c: np.full(n, 100.0) for c in ("Open", "High", "Low", "Close")}, index=index
    )
    prices["Volume"] = 1000.0
    analyzer = TechnicalAnalyzer(prices)
    for name, values in columns.items():
        analyzer.df[name] = values
    return analyzer


@pytest.mark.parametrize(
    "macd, signal, expected",
    [
        ([1.0, 2.0], [1.5, 1.5], "bullish"),  # crossed above on the last bar
        ([2.0, 1.0], [1.5, 1.5], "bearish"),
        ([1.6, 2.0], [1.5, 1.5], None),  # above on both bars: a state, not a cross
        ([1.0, 1.2], [1.5, 1.5], None),
        ([1.5, 2.0], [1.5, 1.5], "bullish"),  # from touching to above
    ],
)
def test_macd_cross_is_only_the_bar_it_happens(macd, signal, expected):
    state = _analyzer(MACD=macd, MACD_signal=signal).crossovers()
    assert state["macd_cross"] == expected


def test_ma_regime_and_cross():
    golden = _analyzer(SMA_50=[99.0, 101.0], SMA_200=[100.0, 100.0]).crossovers()
    assert golden["ma_cross"] == "golden" and golden["ma_regime"] == "bullish"
    above = _analyzer(SMA_50=[101.0, 102.0], SMA_200=[100.0, 100.0]).crossovers()
    assert above["ma_cross"] is None and above["ma_regime"] == "bullish"
    death = _analyzer(SMA_50=[101.0, 99.0], SMA_200=[100.0, 100.0]).crossovers()
    assert death["ma_cross"] == "death" and death["ma_regime"] == "bearish"


def test_missing_values_give_no_state():
    state = _analyzer(MACD=[np.nan, 1.0], MACD_signal=[1.0, 0.5]).crossovers()
    assert state == {"macd_cross": None, "ma_regime": None, "ma_cross": None}


def test_ma_trend_text_names_a_cross_only_on_the_cross_bar():
    above = _analyzer(SMA_50=[101.0, 102.0], SMA_200=[100.0, 100.0]).generate_signals()
    assert above["MA_Trend"] == "Bullish (SMA 50 above SMA 200)"
    golden = _analyzer(SMA_50=[99.0, 101.0], SMA_200=[100.0, 100.0]).generate_signals()
    assert golden["MA_Trend"].startswith("Golden Cross today")
