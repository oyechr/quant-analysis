"""
Tests for portfolio exposure (src/portfolio/exposure.py). All data is
synthetic; real holdings never go in tests.
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.portfolio import Holding, HoldingReview
from src.portfolio.exposure import (
    beta,
    effective_number,
    measure_exposure,
    risk_contributions,
    shrunk_covariance,
    to_base_currency,
    weekly_returns,
    weighted_median,
)


def _series(values, start="2025-01-06", tz=None, freq="B"):
    index = pd.date_range(start, periods=len(values), freq=freq, tz=tz)
    return pd.Series(np.asarray(values, dtype=float), index=index)


def _walk(n, seed, vol=0.02):
    rng = np.random.default_rng(seed)
    return 100.0 * np.cumprod(1 + rng.normal(0.0, vol, n))


# ==================== Currency ====================


class TestToBaseCurrency:
    def test_converts_with_the_daily_rate(self):
        close = _series([10.0, 11.0, 12.0], tz="America/New_York")
        fx = _series([10.0, 10.5, 11.0], tz="Europe/London")
        converted = to_base_currency(close, "USD", "NOK", lambda s: fx if s == "USDNOK=X" else None)
        assert list(converted) == pytest.approx([100.0, 115.5, 132.0])
        assert converted.index.tz is None  # trading dates, so exchanges line up

    def test_minor_units_become_major(self):
        close = _series([250.0, 260.0])  # pence
        fx = _series([13.0, 13.0])
        converted = to_base_currency(close, "GBp", "NOK", lambda s: fx if s == "GBPNOK=X" else None)
        assert list(converted) == pytest.approx([32.5, 33.8])

    def test_same_currency_needs_no_rate(self):
        close = _series([1.0, 2.0])
        assert list(to_base_currency(close, "NOK", "NOK", lambda s: None)) == [1.0, 2.0]

    def test_rate_carried_over_a_day_without_fx(self):
        close = _series([10.0, 10.0, 10.0])
        fx = pd.Series([10.0, 12.0], index=close.index[[0, 2]])
        converted = to_base_currency(close, "USD", "NOK", lambda s: fx)
        assert list(converted) == pytest.approx([100.0, 100.0, 120.0])

    def test_missing_rate(self):
        assert to_base_currency(_series([1.0]), "USD", "NOK", lambda s: None) is None


# ==================== Returns and covariance ====================


def test_weekly_returns_align_different_holiday_calendars():
    days = pd.bdate_range("2025-01-06", periods=400)
    oslo = pd.Series(_walk(400, 1), index=days).drop(days[[4, 9]])  # two Oslo holidays
    us = pd.Series(_walk(400, 2), index=days).drop(days[[14]])
    returns = weekly_returns({"A.OL": oslo, "B": us}, min_weeks=52)
    assert list(returns.columns) == ["A.OL", "B"]
    assert not returns.isna().any().any()
    assert all(d.dayofweek == 4 for d in returns.index)  # Fridays
    # A week with a holiday uses the last close before it
    friday = returns.index[1]
    expected = oslo[:friday].iloc[-1] / oslo[: returns.index[0]].iloc[-1] - 1
    assert returns.loc[friday, "A.OL"] == pytest.approx(expected)


def test_weekly_returns_drop_short_histories():
    days = pd.bdate_range("2025-01-06", periods=400)
    long = pd.Series(_walk(400, 1), index=days)
    short = pd.Series(_walk(100, 2), index=days[-100:])  # about 20 weeks
    returns = weekly_returns({"LONG": long, "NEW": short}, min_weeks=52)
    assert list(returns.columns) == ["LONG"]
    assert len(returns) >= 70  # not cut to the short history


def _ledoit_wolf_loops(x: np.ndarray) -> float:
    """Shrinkage intensity straight from Ledoit and Wolf (2004), section 2 and appendix B."""
    t, n = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / t
    r = s / np.sqrt(np.outer(np.diag(s), np.diag(s)))
    r_bar = (r.sum() - n) / (n * (n - 1))  # average off-diagonal correlation
    f = r_bar * np.sqrt(np.outer(np.diag(s), np.diag(s)))
    np.fill_diagonal(f, np.diag(s))
    pi = sum(np.mean((x[:, i] * x[:, j] - s[i, j]) ** 2) for i in range(n) for j in range(n))

    def theta(k, i, j):  # asymptotic covariance of s_kk and s_ij
        return np.mean((x[:, k] ** 2 - s[k, k]) * (x[:, i] * x[:, j] - s[i, j]))

    rho = sum(np.mean((x[:, i] ** 2 - s[i, i]) ** 2) for i in range(n))
    for i in range(n):
        for j in range(n):
            if i != j:
                rho += (r_bar / 2) * (
                    math.sqrt(s[j, j] / s[i, i]) * theta(i, i, j)
                    + math.sqrt(s[i, i] / s[j, j]) * theta(j, i, j)
                )
    gamma = ((f - s) ** 2).sum()
    return max(0.0, min(1.0, (pi - rho) / gamma / t))


class TestShrunkCovariance:
    def _returns(self, weeks, n=5, seed=3):
        rng = np.random.default_rng(seed)
        market = rng.normal(0, 0.02, weeks)
        data = {f"T{i}": market * (0.5 + 0.2 * i) + rng.normal(0, 0.03, weeks) for i in range(n)}
        return pd.DataFrame(data)

    def test_matches_the_formulas_in_the_paper(self):
        returns = self._returns(60)
        _, shrinkage = shrunk_covariance(returns)
        assert shrinkage == pytest.approx(_ledoit_wolf_loops(returns.to_numpy()))
        assert 0 < shrinkage < 1

    def test_keeps_the_variances_and_stays_positive_definite(self):
        returns = self._returns(60)
        cov, _ = shrunk_covariance(returns)
        sample = returns.cov(ddof=0)
        assert np.diag(cov) == pytest.approx(np.diag(sample))
        assert np.allclose(cov, cov.T)
        assert np.linalg.eigvalsh(cov.to_numpy()).min() > 0

    def test_more_history_means_less_shrinkage(self):
        _, short = shrunk_covariance(self._returns(40))
        _, long = shrunk_covariance(self._returns(4000))
        assert long < short


def test_risk_contributions():
    # Uncorrelated, equal weights: shares follow the variances (0.04 vs 0.01)
    cov = pd.DataFrame([[0.04, 0.0], [0.0, 0.01]], index=["A", "B"], columns=["A", "B"])
    shares = risk_contributions(pd.Series({"A": 0.5, "B": 0.5}), cov)
    assert list(shares) == pytest.approx([0.8, 0.2])
    # Inverse-volatility weights equalize them when assets are uncorrelated
    shares = risk_contributions(pd.Series({"A": 1 / 3, "B": 2 / 3}), cov)
    assert list(shares) == pytest.approx([0.5, 0.5])


def test_beta():
    rng = np.random.default_rng(0)
    index = pd.date_range("2024-01-05", periods=104, freq="W-FRI")
    bench = pd.Series(rng.normal(0, 0.02, 104), index=index)
    stock = 1.5 * bench + pd.Series(rng.normal(0, 0.002, 104), index=index)
    assert beta(stock, bench) == pytest.approx(1.5, abs=0.05)
    assert beta(stock.iloc[:20], bench) is None  # too few weeks


def test_effective_number_and_weighted_median():
    assert effective_number([0.25] * 4) == pytest.approx(4)
    assert effective_number([0.7, 0.1, 0.1, 0.1]) == pytest.approx(1 / 0.52)
    assert effective_number([]) is None
    assert weighted_median([(0.6, 1.0), (0.2, 5.0), (0.2, 9.0)]) == 1.0
    assert weighted_median([(0.2, 1.0), (0.3, 5.0), (0.5, 9.0)]) == 5.0


# ==================== Exposure ====================


def _holding(ticker, weight, sector="Energy", country="Norway", fund=False, **chars):
    review = HoldingReview(
        holding=Holding(ticker, ticker, 10, None, "NOK"),
        weight=weight,
        sector="Fund" if fund else sector,
        country=country,
        is_fund=fund,
        listing_currency="NOK",
        characteristics=chars,
        vet={"header": {"dimensions": {"valuation": 60.0, "fundamental": 40.0}}},
    )
    review.vet["header"]["score"] = 50.0
    return review


def test_measure_exposure():
    days = pd.bdate_range("2024-10-01", periods=520)
    rng = np.random.default_rng(5)
    world = 100 * np.cumprod(1 + rng.normal(0, 0.01, 520))
    closes = {
        "OIL.OL": pd.Series(_walk(520, 1, vol=0.03), index=days),
        "BANK.OL": pd.Series(_walk(520, 2, vol=0.01), index=days),
        "FUND": pd.Series(world * 1.0, index=days),
        "NEW.OL": pd.Series(_walk(60, 4), index=days[-60:]),
    }
    reviews = [
        _holding("OIL.OL", 0.4, earnings_yield=0.10, roe=0.15),
        _holding("BANK.OL", 0.3, sector="Financial Services", earnings_yield=0.08, roe=0.12),
        _holding("FUND", 0.2, fund=True, country="Ireland", earnings_yield=0.05),
        _holding("NEW.OL", 0.1, sector="Technology", earnings_yield=0.02, roe=0.30),
    ]

    measured = measure_exposure(
        reviews, closes, {"World": pd.Series(world, index=days)}, local_closes=closes
    )
    exposure, correlations = measured.summary, measured.correlations
    assert list(measured.covariance.columns) == ["OIL.OL", "BANK.OL", "FUND"]

    assert exposure["excluded"] == ["NEW.OL"]
    assert exposure["coverage"] == pytest.approx(0.9)
    assert sum(r.risk_share for r in reviews if r.risk_share is not None) == pytest.approx(1.0)
    assert reviews[3].risk_share is None
    # The 3%-a-day stock carries most of the risk
    oil, bank = reviews[0], reviews[1]
    assert oil.risk_share > 0.4 > bank.risk_share
    assert reviews[2].beta == pytest.approx(1.0, abs=0.01)  # the fund is the world index
    assert 0.05 < exposure["volatility"] < 0.5
    assert list(correlations.columns) == ["OIL.OL", "BANK.OL", "FUND"]

    sectors = {g["name"]: g for g in exposure["by_sector"]}
    assert sectors["Energy"]["weight"] == pytest.approx(0.4)
    assert sectors["Energy"]["risk"] == pytest.approx(oil.risk_share)
    assert sectors["Technology"]["risk"] is None
    countries = [g["name"] for g in exposure["by_country"]]
    assert countries == ["Norway", "Fund"]

    tilts = {f["factor"]: f for f in exposure["factors"]}
    value = tilts["Value"]
    # Sorted: 2% (weight 0.1), 8% (0.3), 10% (0.4): half the 0.8 is reached at 8%
    assert value["median"] == 0.08
    assert value["low"]["ticker"] == "NEW.OL" and value["high"]["ticker"] == "OIL.OL"
    assert value["coverage"] == pytest.approx(1.0)  # the fund is left out
    assert tilts["Low volatility"]["coverage"] == pytest.approx(0.7 / 0.8)
    assert exposure["dimensions"]["valuation"] == pytest.approx(60.0)
    assert exposure["top5"] == pytest.approx(1.0)
    assert exposure["effective_positions"] == pytest.approx(1 / 0.3)
