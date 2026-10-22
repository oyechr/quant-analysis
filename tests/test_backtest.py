"""
Tests for Phase 5: the price-only backtest. Offline: synthetic prices, or the
fake_market fixture with long price histories.
"""

import json
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from src.backtest import (
    backtest_months,
    backtest_to_dict,
    band_table,
    engine,
    history_period,
    mean_ci,
    monthly_ic,
    monthly_spread,
    newey_west_se,
    render_text,
    run_backtest,
)
from src.backtest.engine import month_end_positions, ticker_observations
from src.cli import cli
from src.data_fetcher import DataFetcher
from src.scoring import ScoringConfig
from tests.conftest import make_prices

TODAY = date(2026, 10, 22)


def _steady(symbol: str, days: int = 600, daily: float = 0.001, end: str = "2026-10-21"):
    """Prices growing by a fixed daily rate, so forward returns are known exactly."""
    prices = make_prices(symbol, days=days, end=pd.Timestamp(end))
    close = 100.0 * (1 + daily) ** np.arange(days)
    for column in ("Open", "High", "Low", "Close"):
        prices[column] = close
    return prices


class TestCalendar:
    def test_history_period_covers_lookback(self):
        assert history_period(1) == "2y"
        assert history_period(4) == "5y"
        assert history_period(5) == "10y"
        assert history_period(10) == "max"

    def test_months_are_complete_months_oldest_first(self):
        months = backtest_months(1, TODAY)
        assert [str(m) for m in (months[0], months[-1])] == ["2025-10", "2026-09"]
        assert len(months) == 12

    def test_month_ends_use_exchange_dates_for_utc_stamps(self):
        """Cached prices come back in UTC: Oslo's 1 June midnight is 31 May 22:00 UTC."""
        oslo = pd.DatetimeIndex(["2026-05-29", "2026-06-01", "2026-06-30"]).tz_localize(
            "Europe/Oslo"
        )
        ends = month_end_positions(oslo.tz_convert("UTC"))
        assert ends[pd.Period("2026-05", "M")] == 0
        assert ends[pd.Period("2026-06", "M")] == 2


class TestObservations:
    def _rows(self, prices, bench, months=None, horizons=(1, 3)):
        months = months or backtest_months(1, TODAY)
        return ticker_observations("T", prices, bench, "^GSPC", months, horizons, ScoringConfig())

    def test_forward_returns_and_excess(self):
        prices = _steady("T", daily=0.002)
        bench = _steady("^GSPC", daily=0.001)

        rows = {r["month"]: r for r in self._rows(prices, bench)}

        row = rows["2026-06"]
        close = prices["Close"]
        ends = month_end_positions(pd.DatetimeIndex(prices.index))
        june, july = ends[pd.Period("2026-06", "M")], ends[pd.Period("2026-07", "M")]
        assert row["ret_1m"] == pytest.approx(close.iloc[july] / close.iloc[june] - 1)
        bench_ret = 1.001 ** (july - june) - 1  # same calendar, so the same bars
        assert row["excess_1m"] == pytest.approx(row["ret_1m"] - bench_ret)
        assert row["composite"] is not None and row["signal"] is not None
        assert row["momentum"] > 0 and row["low_vol"] is not None

    def test_beta_adjusted_return(self, default_config):
        prices = make_prices("T", days=600, end=pd.Timestamp("2026-10-21"), seed=5)
        bench = make_prices("^GSPC", days=600, end=pd.Timestamp("2026-10-21"), seed=6)

        row = {r["month"]: r for r in self._rows(prices, bench, horizons=(3,))}["2026-03"]

        rf = (1 + default_config.risk_free_rate) ** (3 / 12) - 1
        bench_ret = row["ret_3m"] - row["excess_3m"]
        assert row["beta"] is not None
        assert row["alpha_3m"] == pytest.approx(
            (row["ret_3m"] - rf) - row["beta"] * (bench_ret - rf)
        )

    def test_no_return_past_the_last_complete_month(self):
        rows = {r["month"]: r for r in self._rows(_steady("T"), _steady("^GSPC"))}
        assert rows["2026-08"]["ret_1m"] is not None
        assert rows["2026-09"]["ret_1m"] is None  # October isn't over
        assert rows["2026-07"]["ret_3m"] is None

    def test_signals_use_no_future_prices(self):
        prices = make_prices("T", days=600, end=pd.Timestamp("2026-10-21"), seed=3)
        bench = make_prices("^GSPC", days=600, end=pd.Timestamp("2026-10-21"), seed=4)
        months = [pd.Period("2026-03", "M"), pd.Period("2026-09", "M")]
        before = self._rows(prices, bench, months)[0]

        crashed = prices.copy()
        after_march = crashed.index > pd.Timestamp("2026-04-01", tz=crashed.index.tz)
        crashed.loc[after_march, ["Open", "High", "Low", "Close"]] *= 0.5
        after = self._rows(crashed, bench, months)[0]

        signals = ("composite", "technical", "risk", "momentum", "low_vol", "signal")
        assert {k: before[k] for k in signals} == {k: after[k] for k in signals}
        assert after["ret_1m"] < before["ret_1m"]

    def test_too_little_history_skips_months(self):
        rows = self._rows(_steady("T", days=300), _steady("^GSPC"))
        assert all(r["month"] >= "2026-08" for r in rows)


class TestStats:
    def test_newey_west_without_lags_is_the_plain_standard_error(self):
        values = np.array([1.0, 3.0, 2.0, 5.0, 4.0])
        assert newey_west_se(values, 0) == pytest.approx(values.std() / math.sqrt(5))

    def test_newey_west_widens_for_positively_correlated_series(self):
        trend = np.repeat([1.0, -1.0], 10)  # long runs: strong autocorrelation
        assert newey_west_se(trend, 3) > newey_west_se(trend, 0)

    def test_mean_ci(self):
        ci = mean_ci(pd.Series([1.0, 2.0, 3.0, None]))
        assert ci["mean"] == 2.0 and ci["n"] == 3 and ci["low"] < 2.0 < ci["high"]
        assert mean_ci(pd.Series([1.0])) is None

    def _obs(self, months=3, tickers=20, noise=0.0, seed=0):
        rng = np.random.default_rng(seed)
        rows = []
        for m in range(months):
            for t in range(tickers):
                rows.append(
                    {
                        "month": f"2026-0{m + 1}",
                        "ticker": f"T{t}",
                        "momentum": float(t),
                        "excess_1m": t / 100 + rng.normal(0, noise),
                    }
                )
        return pd.DataFrame(rows)

    def test_perfect_signal(self):
        obs = self._obs()
        assert monthly_ic(obs, "momentum", "excess_1m").tolist() == pytest.approx([1.0] * 3)
        # top fifth (16-19) minus bottom fifth (0-3): 0.175 - 0.015
        assert monthly_spread(obs, "momentum", "excess_1m").tolist() == pytest.approx([0.16] * 3)

    def test_thin_months_are_skipped(self):
        obs = self._obs(tickers=5)
        assert monthly_ic(obs, "momentum", "excess_1m").isna().all()

    def test_band_table(self):
        obs = pd.DataFrame(
            {
                "month": ["2026-01"] * 4 + ["2026-02"] * 4,
                "signal": ["Buy", "Buy", "Sell", None] * 2,
                "excess_1m": [0.02, 0.04, -0.01, 0.5, 0.0, 0.02, -0.03, 0.5],
            }
        )
        rows = {r["band"]: r for r in band_table(obs, [1])}

        assert rows["Buy"]["observations"] == 4 and rows["Buy"]["share"] == pytest.approx(4 / 6)
        assert rows["Buy"]["1m"]["mean"]["mean"] == pytest.approx(0.02)  # months: 0.03, 0.01
        assert rows["Buy"]["1m"]["beat"] == pytest.approx(0.75)
        assert rows["Sell"]["1m"]["mean"]["mean"] == pytest.approx(-0.02)
        assert rows["Strong Buy"]["observations"] == 0 and rows["Strong Buy"]["1m"]["mean"] is None
        assert rows["All"]["observations"] == 6  # unscored rows left out


@pytest.fixture
def long_market(fake_market):
    """Ten tickers and the S&P with two and a half years of prices."""
    end = pd.Timestamp.now().normalize()
    for i, symbol in enumerate(["^GSPC", *[f"T{i}" for i in range(10)]]):
        fake_market.price_overrides[symbol] = make_prices(symbol, days=650, end=end, seed=i)
    return fake_market


class TestRunBacktest:
    def test_end_to_end(self, long_market, tmp_path):
        long_market.failing.add("BAD")
        tickers = [f"T{i}" for i in range(10)] + ["BAD"]

        result = run_backtest(
            tickers, DataFetcher(cache_dir=str(tmp_path)), years=1, horizons=(1, 3)
        )

        assert result.tickers == 10 and "BAD" in result.errors
        assert len(result.observations) == 120  # 10 tickers x 12 months
        data = backtest_to_dict(result)
        excess = data["summary"]["excess"]
        assert (
            excess["signals"]["momentum"]["1m"]["ic"]["n"] == 11
        )  # the last month has no 1m return
        assert {row["band"] for row in excess["bands"]} >= {"Hold", "All"}
        assert set(data["summary"]) == {"excess", "alpha", "ret"}

        text = render_text(data)
        titles = (
            "RANK IC",
            "QUINTILE SPREAD",
            "HIT RATE",
            "BETA-ADJUSTED",
            "SIGNAL BANDS",
            "CAVEATS",
        )
        for title in titles:
            assert title in text
        assert "Not tested: BAD" in text


def test_cli_backtest(long_market, tmp_path, monkeypatch):
    # The real scoring is covered above; keep this one fast
    monkeypatch.setattr(
        engine,
        "score_window",
        lambda window, *_: {
            "composite": 55.0,
            "signal": "Hold",
            "technical": 50.0,
            "risk": 60.0,
            "momentum": float(window["Close"].iloc[-1]),
            "low_vol": 1.0,
        },
    )
    tickers = [f"T{i}" for i in range(10)]
    out = CliRunner().invoke(
        cli, ["--output-dir", str(tmp_path), "backtest", *tickers, "--years", "1", "--json"]
    )

    assert out.exit_code == 0, out.output
    data = json.loads(out.stdout)  # saved paths go to stderr
    assert data["meta"]["tickers"] == 10 and data["meta"]["horizons"] == [1, 3, 6]
    saved = sorted(p.name for p in (tmp_path / "_backtests").iterdir())
    assert len(saved) == 3 and saved[0].endswith(".json")


def test_cli_rejects_bad_horizons(tmp_path):
    out = CliRunner().invoke(cli, ["backtest", "AAPL", "--horizons", "0,x"])
    assert out.exit_code != 0
