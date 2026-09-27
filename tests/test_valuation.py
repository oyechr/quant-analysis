"""
Tests for the two-stage DCF, the reverse DCF, WACC, and the Monte Carlo DCF.
"""

import pandas as pd
import pytest

from src.analysis.valuation import (
    GROWTH_BOUNDS,
    ValuationAnalyzer,
    dcf_enterprise_value,
    implied_growth,
)
from src.vetting import fair_value_range, render_text


def _statements(fcf=(100.0, 100.0, 100.0), debt=200.0, cash=50.0, interest=10.0, tax=0.25):
    years = [pd.Timestamp(f"{2025 - i}-12-31") for i in range(len(fcf))]
    cash_flow = pd.DataFrame({d: {"Free Cash Flow": v} for d, v in zip(years, fcf)})
    balance = pd.DataFrame(
        {
            years[0]: {
                "Total Debt": debt,
                "Cash Cash Equivalents And Short Term Investments": cash,
            }
        }
    )
    income = pd.DataFrame({years[0]: {"Interest Expense": interest, "Tax Rate For Calcs": tax}})
    return {
        "cash_flow_annual": cash_flow,
        "balance_sheet_annual": balance,
        "income_stmt_annual": income,
    }


def _analyzer(beta=1.0, market_cap=1800.0, price=18.0, **statements):
    info = {"beta": beta, "market_cap": market_cap, "shares_outstanding": 100.0}
    prices = pd.DataFrame({"Close": [price]})
    return ValuationAnalyzer("T", info, price_data=prices, fundamentals=_statements(**statements))


class TestDcfCore:
    def test_zero_growth_is_a_perpetuity(self):
        # FCF 100 forever at 10% is worth 1000
        assert dcf_enterprise_value(100.0, 0.0, 10.0, 0.0)[0] == pytest.approx(1000.0)

    def test_growth_fades_to_terminal(self):
        # Starting at the terminal rate is a plain growing perpetuity: 100 x 1.02 / (0.1 - 0.02)
        value = dcf_enterprise_value(100.0, 2.0, 10.0, 2.0)[0]
        assert value == pytest.approx(100 * 1.02 / 0.08)

    def test_vectorized_rows_match_scalar_calls(self):
        rows = dcf_enterprise_value(100.0, [0.0, 5.0], [10.0, 9.0], [2.0, 2.5])
        assert rows[1] == pytest.approx(dcf_enterprise_value(100.0, 5.0, 9.0, 2.5)[0])

    def test_implied_growth_round_trip(self):
        equity = dcf_enterprise_value(100.0, 12.0, 9.0, 2.5)[0] - 300.0
        growth = implied_growth(equity, 100.0, 9.0, 2.5, net_debt=300.0)
        assert growth == pytest.approx(12.0, abs=1e-6)

    def test_implied_growth_out_of_bounds(self):
        assert implied_growth(1e12, 100.0, 9.0, 2.5) is None


class TestDiscountRate:
    def test_blume_adjusted_beta_and_default_premium(self):
        cost, details = _analyzer(beta=1.6)._cost_of_equity()
        assert details["beta_adjusted"] == pytest.approx(0.67 * 1.6 + 0.33)
        assert cost == pytest.approx(4.0 + details["beta_adjusted"] * 5.0)

    def test_negative_beta_falls_back_to_market(self):
        _, details = _analyzer(beta=-0.73)._cost_of_equity()
        assert details["beta_adjusted"] == 1.0

    def test_wacc_weights_after_tax_debt(self):
        # E 1800, D 200: 0.9 x 9% + 0.1 x max(10/200 = 5%, rf 4%) x (1 - 0.25)
        wacc, details = _analyzer()._estimate_wacc_details()
        assert details["debt_weight"] == pytest.approx(0.1)
        assert wacc == pytest.approx(0.9 * 9.0 + 0.1 * 5.0 * 0.75)


class TestDcfValuation:
    def test_net_debt_comes_from_the_balance_sheet(self):
        dcf = _analyzer().calculate_dcf_valuation()
        assert dcf["assumptions"]["net_debt"] == 150.0
        assert dcf["equity_value"] == pytest.approx(dcf["enterprise_value"] - 150.0)

    def test_collapsing_fcf_is_clamped(self):
        dcf = _analyzer(fcf=(20.0, 50.0, 100.0)).calculate_dcf_valuation()
        assert dcf["assumptions"]["growth_rate_historical"] < -50
        assert dcf["growth_rate_used"] == GROWTH_BOUNDS[0]

    def test_price_implies_growth(self):
        dcf = _analyzer().calculate_dcf_valuation()
        # Repricing the DCF at the implied growth gives back the market cap
        equity = (
            dcf_enterprise_value(100.0, dcf["implied_growth_pct"], dcf["wacc_used"], 2.5)[0] - 150.0
        )
        assert equity == pytest.approx(1800.0, rel=1e-6)

    def test_negative_fcf_is_not_valued(self):
        dcf = _analyzer(fcf=(-10.0, 50.0)).calculate_dcf_valuation()
        assert dcf["intrinsic_value_per_share"] is None
        assert "Negative" in dcf["error"]

    def test_monte_carlo_centres_on_the_dcf(self):
        analyzer = _analyzer()
        dcf = analyzer.calculate_dcf_valuation()["intrinsic_value_per_share"]
        mc = analyzer.calculate_monte_carlo_valuation(n_simulations=4000)
        assert mc["confidence_intervals"]["ci_10"] < dcf < mc["confidence_intervals"]["ci_90"]
        assert 0.0 <= mc["probability_undervalued"] <= 1.0

    def test_ddm_uses_cost_of_equity(self):
        analyzer = _analyzer()
        analyzer.dividends_data = pd.Series(
            [1.0] * 8, index=pd.date_range("2024-01-01", periods=8, freq="QS")
        )
        ddm = analyzer.calculate_ddm_valuation(growth_rate=3.0)
        assert ddm["required_return_used"] == pytest.approx(9.0)


def test_vet_shows_the_reverse_dcf():
    analyzer = _analyzer()
    report = {
        "ticker": "T",
        "info": {"current_price": 18.0, "currency": "USD"},
        "valuation_analysis": {"dcf_valuation": analyzer.calculate_dcf_valuation()},
    }
    data = {"ticker": "T", "header": {}, "fair_value": fair_value_range(report)}

    text = render_text(data)

    assert "the price implies" in text
    assert "fading to 2.5% over 10y" in text
