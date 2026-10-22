"""
Tests for `quant review`. Portfolios here are synthetic (made-up tickers,
names and amounts); real holdings never go in tests.
"""

import json

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import cli
from src.data_fetcher import DataFetcher
from src.pipeline import AnalysisOptions
from src.portfolio import (
    Holding,
    HoldingReview,
    decide_action,
    load_portfolio,
    render_text,
    review_portfolio,
)
from src.portfolio.review import (
    ADD,
    CHECK,
    EXIT,
    HOLD,
    REVIEW,
    TRIM,
    is_fund,
    is_overweight,
)


def _write_portfolio(path, rows):
    pd.DataFrame(
        rows, columns=["ticker", "name", "account", "shares", "cost_basis", "currency"]
    ).to_csv(path, index=False)
    return path


# ==================== Input ====================


def test_load_portfolio_combines_accounts(tmp_path):
    path = _write_portfolio(
        tmp_path / "portfolio.csv",
        [
            ["SMB.OL", "Sample Bank", "ASK", 10, 100.0, "NOK"],
            ["SMB.OL", "Sample Bank", "AF", 30, 200.0, "NOK"],
            ["TST", "Test Corp", "AF", 5, 50.0, "USD"],
            ["", "Unknown Fund", "AF", 1, 1.0, "EUR"],
        ],
    )

    holdings, unmapped = load_portfolio(path)

    by_ticker = {h.ticker: h for h in holdings}
    assert set(by_ticker) == {"SMB.OL", "TST"}
    bank = by_ticker["SMB.OL"]
    assert bank.shares == 40
    assert bank.cost_basis == pytest.approx(175.0)  # (10*100 + 30*200) / 40
    assert bank.accounts == ["ASK", "AF"]
    assert unmapped == ["Unknown Fund"]


def test_load_portfolio_keeps_numeric_account_labels(tmp_path):
    path = _write_portfolio(tmp_path / "p.csv", [["TST", "Test Corp", "0012345", 1, None, "USD"]])
    holdings, _ = load_portfolio(path)
    assert holdings[0].accounts == ["0012345"]
    assert holdings[0].cost_basis is None


# ==================== Rules ====================


def _review(call="Watch", score=55.0, weight=0.05, target=0.05, **kwargs):
    """A reviewed holding; a "Pass" call comes with a Sell signal unless flags are given."""
    holding = Holding(
        ticker=kwargs.pop("ticker", "TST"),
        name="Test Corp",
        shares=10,
        cost_basis=100.0,
        currency="USD",
        accounts=kwargs.pop("accounts", ["AF"]),
    )
    flags = kwargs.pop("flags", [])
    signal = kwargs.pop("signal", "Sell" if call == "Pass" and not flags else "Hold")
    vet = {
        "header": {"score": score, "signal": signal},
        "verdict": {"call": call, "reasons": [f"{signal} {score}/100", "no red flags"]},
        "red_flags": [{"severity": "high", "title": title} for title in flags],
    }
    kwargs.setdefault("price", 120.0)
    return HoldingReview(holding=holding, vet=vet, weight=weight, target_weight=target, **kwargs)


class TestDecideAction:
    def test_sell_signal_exits(self):
        action, reasons = decide_action(_review(call="Pass", score=40.0))
        assert action == EXIT
        assert reasons[0] == "Sell 40.0/100"

    def test_red_flag_with_hold_signal_is_review(self):
        review = _review(call="Pass", flags=["Altman Z-Score in distress zone"])
        action, reasons = decide_action(review)
        assert action == REVIEW
        assert reasons[0] == "red flag: altman z-score in distress zone"
        assert reasons[-1] == "Hold 55.0/100; look into the flag before selling"

    def test_sell_signal_with_red_flag_exits(self):
        review = _review(call="Pass", signal="Sell", flags=["Negative free cash flow"])
        assert decide_action(review)[0] == EXIT

    def test_review_beats_trim(self):
        review = _review(call="Pass", flags=["Share count dilution"], weight=0.2, target=0.05)
        assert decide_action(review)[0] == REVIEW

    def test_overweight_trims(self):
        action, reasons = decide_action(_review(weight=0.12, target=0.05))
        assert action == TRIM
        assert "12.0% vs risk-parity target 5.0%" in reasons[0]

    def test_slightly_over_target_holds(self):
        # 1.5x the target but less than 2 points above it: noise, not a trim
        assert decide_action(_review(weight=0.03, target=0.019))[0] == HOLD

    def test_moving_with_a_larger_holding_trims(self):
        action, reasons = decide_action(_review(moves_with=("BIG", 0.91)))
        assert action == TRIM
        assert "moves with BIG" in reasons[0]

    def test_look_deeper_below_target_adds(self):
        action, reasons = decide_action(_review(call="Look deeper", weight=0.02, target=0.05))
        assert action == ADD
        assert reasons[0] == "weight 2.0% vs risk-parity target 5.0%"

    def test_look_deeper_at_target_holds(self):
        assert decide_action(_review(call="Look deeper", weight=0.05, target=0.05))[0] == HOLD

    def test_look_deeper_but_redundant_trims(self):
        review = _review(call="Look deeper", weight=0.02, target=0.05, moves_with=("BIG", 0.85))
        assert decide_action(review)[0] == TRIM

    def test_exit_beats_trim(self):
        review = _review(call="Pass", weight=0.2, target=0.05, moves_with=("BIG", 0.9))
        assert decide_action(review)[0] == EXIT

    def test_watch_holds(self):
        action, reasons = decide_action(_review(call="Watch"))
        assert action == HOLD
        assert reasons == ["Hold 55.0/100", "no red flags"]

    def test_no_data_is_check(self):
        review = HoldingReview(
            holding=Holding("BAD", "Bad", 1, None, "NOK"), error="No data returned"
        )
        action, reasons = decide_action(review)
        assert action == CHECK
        assert "No data returned" in reasons[0]

    def test_fund_is_never_exit_review_or_add(self):
        assert decide_action(_review(call="Pass", is_fund=True))[0] == HOLD
        assert decide_action(_review(call="Pass", flags=["No score"], is_fund=True))[0] == HOLD
        assert (
            decide_action(_review(call="Look deeper", weight=0.01, target=0.05, is_fund=True))[0]
            == HOLD
        )
        assert decide_action(_review(call="Pass", is_fund=True, weight=0.3, target=0.05))[0] == TRIM

    def test_tax_note_when_selling_at_a_gain(self):
        _, reasons = decide_action(_review(call="Pass", gain_pct=40.0, accounts=["AF"]))
        assert reasons[-1] == "selling realizes a 40% gain in AF"
        _, reasons = decide_action(_review(call="Pass", gain_pct=40.0, accounts=["ASK", "AF"]))
        assert reasons[-1].startswith("sell from the ASK first")
        _, reasons = decide_action(_review(call="Pass", gain_pct=-10.0, accounts=["AF"]))
        assert not any("gain" in r for r in reasons)


def test_is_overweight_needs_both_ratio_and_gap():
    assert is_overweight(0.10, 0.05)
    assert not is_overweight(0.06, 0.05)  # under 1.5x
    assert not is_overweight(0.015, 0.005)  # 3x but only 1 point over
    assert not is_overweight(None, 0.05)


def test_is_fund():
    assert is_fund({"quote_type": "ETF"})
    assert not is_fund({"quote_type": "EQUITY"}, "Some UCITS ETF")  # quote type wins
    assert is_fund({}, "Vanguard FTSE All-World UCITS ETF")
    assert not is_fund({}, "Sample Bank")


# ==================== End to end (fake market) ====================


@pytest.fixture
def review_market(fake_market, price_factory):
    # USDNOK = 10; TWIN.OL is an exact copy of BIG.OL's prices (correlation 1)
    fx = price_factory("USDNOK=X", seed=1)
    fx["Close"] = 10.0
    big = price_factory("BIG.OL", seed=11)
    fake_market.price_overrides.update({"USDNOK=X": fx, "BIG.OL": big, "TWIN.OL": big.copy()})
    fake_market.info_overrides.update(
        {
            "BIG.OL": {"currentPrice": float(big["Close"].iloc[-1]), "sector": "Energy"},
            "TWIN.OL": {"currentPrice": float(big["Close"].iloc[-1]), "sector": "Energy"},
            "TST": {"currentPrice": 50.0, "beta": 1.2},
            "FUND.DE": {"quoteType": "ETF", "currency": "EUR", "currentPrice": 30.0},
        }
    )
    fake_market.failing.add("BAD.OL")
    return fake_market


def _holdings():
    return [
        Holding("BIG.OL", "Big Energy", 100, 80.0, "NOK", ["ASK"]),
        Holding("TWIN.OL", "Twin Energy", 10, 80.0, "NOK", ["AF"]),
        Holding("TST", "Test Corp", 20, 40.0, "USD", ["AF"]),
        Holding("BAD.OL", "Broken Ticker", 5, 10.0, "NOK", ["AF"]),
    ]


def test_review_portfolio_end_to_end(review_market, tmp_path):
    fetcher = DataFetcher(cache_dir=str(tmp_path))
    result = review_portfolio(
        _holdings(),
        fetcher=fetcher,
        options=AnalysisOptions(include_context=False),
        workers=1,
        data_dir=str(tmp_path),
    )
    by_ticker = {r.holding.ticker: r for r in result.holdings}

    # Valued in NOK: TST is 20 shares x $50 x 10 NOK/USD
    assert by_ticker["TST"].value == pytest.approx(10_000.0)
    assert by_ticker["TST"].gain_pct == pytest.approx(25.0)  # $50 vs $40 cost
    valued = [r for r in result.holdings if r.weight is not None]
    assert sum(r.weight for r in valued) == pytest.approx(1.0)

    # The smaller of two identical price series is redundant
    assert by_ticker["TWIN.OL"].moves_with[0] == "BIG.OL"
    assert by_ticker["TWIN.OL"].action in (TRIM, EXIT, REVIEW)
    assert by_ticker["BIG.OL"].moves_with is None

    assert by_ticker["BAD.OL"].action == CHECK
    summary = result.summary
    assert summary["correlated_pairs"][0]["pair"] == ["BIG.OL", "TWIN.OL"]
    assert summary["by_currency"][0]["name"] in ("NOK", "USD")
    assert summary["actions"][CHECK] == 1

    text = render_text(result.to_dict())
    assert text.index("PORTFOLIO REVIEW") < text.index("PORTFOLIO\n") < text.index("NOTES")
    assert "BAD.OL" in text


def test_cli_review(review_market, tmp_path):
    portfolio = _write_portfolio(
        tmp_path / "portfolio.csv",
        [
            ["BIG.OL", "Big Energy", "ASK", 100, 80.0, "NOK"],
            ["TST", "Test Corp", "AF", 20, 40.0, "USD"],
            ["", "Unmapped Thing", "AF", 1, 1.0, "NOK"],
        ],
    )

    result = CliRunner().invoke(
        cli,
        [
            "--output-dir",
            str(tmp_path / "data"),
            "review",
            str(portfolio),
            "--save",
            "--workers",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "PORTFOLIO REVIEW" in result.output
    assert "Unmapped Thing" in result.output
    saved = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert {h["ticker"] for h in saved["holdings"]} == {"BIG.OL", "TST"}
    assert (tmp_path / "review.md").exists()
