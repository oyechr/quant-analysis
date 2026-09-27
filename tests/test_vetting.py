"""
Tests for `quant vet`: red-flag rules, peer-relative valuation, 13F fund
activity, verdict helpers, the pipeline signals, and the command end to end.

Red-flag and peer tests use small synthetic report dicts; the end-to-end
tests run the real pipeline against the offline `fake_market`.
"""

import json
from datetime import datetime
from typing import ClassVar

import pandas as pd
import pytest
from click.testing import CliRunner

from src.analysis.fundamental import FundamentalAnalyzer, calculate_pead_signal
from src.cli import cli
from src.data_fetcher import DataFetcher
from src.pipeline import AnalysisOptions, analyze_ticker, pead_history
from src.scoring import ScoringConfig, StockScorer
from src.scoring.dimensions import ValuationScorer
from src.vetting import (
    compare_to_peers,
    fair_value_range,
    find_red_flags,
    fund_activity,
    percentile_rank,
    render_markdown,
    render_text,
    signal_flip_prices,
    vet_ticker,
)
from src.vetting.peers import metric_value, peer_valuation
from src.vetting.red_flags import (
    check_altman,
    check_beneish,
    check_confidence,
    check_currency_mismatch,
    check_dilution,
    check_dividend_coverage,
    check_freshness,
    check_interest_coverage,
    check_negative_fcf,
    check_statement_age,
    share_growth_per_year,
)
from src.vetting.verdict import SIGNAL_BANDS, reprice_report

TODAY = datetime(2026, 9, 28)


def make_report(
    quality=None,
    history=None,
    info=None,
    scoring=None,
    dividend=None,
    warnings=None,
):
    """A minimal report dict with only what the rules read."""
    return {
        "ticker": "TEST",
        "generated_at": TODAY.isoformat(),
        "info": {"sector": "Technology", "currency": "USD", **(info or {})},
        "fundamental_analysis": {
            "analysis": {
                "quality_scores": quality or {},
                "annual_history": history or {},
            }
        },
        "valuation_analysis": {"dividend_analysis": dividend or {}},
        "scoring": scoring
        if scoring is not None
        else {
            "confidence": "High",
            "confidence_score": 0.95,
            "dimensions": {
                d: {"data_coverage": 1.0} for d in ("technical", "fundamental", "risk", "valuation")
            },
        },
        "data_freshness": {"warnings": warnings or []},
    }


# ============================================================
# Red flags: one rule at a time
# ============================================================


class TestBeneish:
    def test_flags_score_above_threshold(self):
        report = make_report(quality={"beneish_m": {"m_score": -1.2, "components_available": 8}})
        [flag] = check_beneish(report, TODAY)
        assert flag.severity == "high"
        assert "-1.20" in flag.detail

    def test_ignores_score_below_threshold(self):
        report = make_report(quality={"beneish_m": {"m_score": -2.5, "components_available": 8}})
        assert check_beneish(report, TODAY) == []

    def test_partial_inputs_downgrade_severity(self):
        report = make_report(quality={"beneish_m": {"m_score": -1.0, "components_available": 3}})
        [flag] = check_beneish(report, TODAY)
        assert flag.severity == "medium"
        assert "3/8" in flag.detail


class TestAltman:
    def test_flags_distress_zone(self):
        [flag] = check_altman(make_report(quality={"altman_z": 1.2}), TODAY)
        assert flag.severity == "high"

    def test_grey_and_safe_zones_pass(self):
        assert check_altman(make_report(quality={"altman_z": 2.5}), TODAY) == []
        assert check_altman(make_report(quality={"altman_z": 4.0}), TODAY) == []

    def test_skipped_for_financials(self):
        report = make_report(quality={"altman_z": 0.3}, info={"sector": "Financial Services"})
        assert check_altman(report, TODAY) == []


class TestNegativeFCF:
    def test_two_of_three_negative(self):
        report = make_report(history={"free_cash_flow": [-5.0, 10.0, -3.0, 50.0]})
        [flag] = check_negative_fcf(report, TODAY)
        assert flag.severity == "medium"
        assert "2 of the last 3" in flag.detail

    def test_all_three_negative_is_high(self):
        report = make_report(history={"free_cash_flow": [-5.0, -1.0, -3.0]})
        assert check_negative_fcf(report, TODAY)[0].severity == "high"

    def test_one_negative_passes(self):
        report = make_report(history={"free_cash_flow": [-5.0, 10.0, 3.0]})
        assert check_negative_fcf(report, TODAY) == []

    def test_only_last_three_years_count(self):
        report = make_report(history={"free_cash_flow": [5.0, 10.0, -3.0, -8.0]})
        assert check_negative_fcf(report, TODAY) == []


class TestDilution:
    PERIODS: ClassVar[list[str]] = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]

    def test_flags_growth_above_three_percent(self):
        shares = [115.0, 110.0, 105.0, 100.0]  # ~4.8%/yr
        report = make_report(history={"periods": self.PERIODS, "shares_outstanding": shares})
        [flag] = check_dilution(report, TODAY)
        assert flag.severity == "medium"

    def test_heavy_dilution_is_high(self):
        shares = [150.0, 130.0, 115.0, 100.0]
        report = make_report(history={"periods": self.PERIODS, "shares_outstanding": shares})
        assert check_dilution(report, TODAY)[0].severity == "high"

    def test_buybacks_pass(self):
        shares = [90.0, 95.0, 98.0, 100.0]
        report = make_report(history={"periods": self.PERIODS, "shares_outstanding": shares})
        assert check_dilution(report, TODAY) == []

    def test_growth_rate_is_annualized(self):
        rate = share_growth_per_year(
            [121.0, None, 100.0], ["2025-12-31", "2024-12-31", "2023-12-31"]
        )
        assert rate == pytest.approx(10.0, abs=0.1)


class TestDividendCoverage:
    def test_payout_over_100_percent(self):
        report = make_report(
            info={"payout_ratio": 1.3, "dividend_yield": 4.0},
            dividend={"pays_dividends": True},
        )
        [flag] = check_dividend_coverage(report, TODAY)
        assert "130%" in flag.detail

    def test_fcf_does_not_cover_dividend(self):
        report = make_report(
            info={"payout_ratio": 0.6},
            dividend={"pays_dividends": True},
            history={"free_cash_flow": [80.0], "dividends_paid": [-100.0]},
        )
        [flag] = check_dividend_coverage(report, TODAY)
        assert "0.80x" in flag.detail

    def test_covered_dividend_passes(self):
        report = make_report(
            info={"payout_ratio": 0.5},
            dividend={"pays_dividends": True},
            history={"free_cash_flow": [300.0], "dividends_paid": [-100.0]},
        )
        assert check_dividend_coverage(report, TODAY) == []

    def test_no_dividend_passes(self):
        report = make_report(info={"payout_ratio": 2.0}, dividend={"pays_dividends": False})
        assert check_dividend_coverage(report, TODAY) == []


class TestInterestCoverage:
    def test_below_two_is_flagged(self):
        report = make_report(history={"interest_coverage": [1.5, 3.0]})
        [flag] = check_interest_coverage(report, TODAY)
        assert flag.severity == "medium"

    def test_below_one_is_high(self):
        report = make_report(history={"interest_coverage": [0.7]})
        assert check_interest_coverage(report, TODAY)[0].severity == "high"

    def test_healthy_coverage_passes(self):
        assert (
            check_interest_coverage(make_report(history={"interest_coverage": [8.0]}), TODAY) == []
        )

    def test_skipped_for_banks(self):
        report = make_report(
            history={"interest_coverage": [0.5]}, info={"sector": "Financial Services"}
        )
        assert check_interest_coverage(report, TODAY) == []


class TestStatementAge:
    def test_old_statements_flagged(self):
        report = make_report(history={"periods": ["2025-03-31"]})  # 18 months before TODAY
        [flag] = check_statement_age(report, TODAY)
        assert "2025-03-31" in flag.detail

    def test_recent_statements_pass(self):
        assert check_statement_age(make_report(history={"periods": ["2025-12-31"]}), TODAY) == []


class TestConfidence:
    def test_low_confidence_flagged(self):
        report = make_report(
            scoring={
                "confidence": "Low",
                "confidence_score": 0.4,
                "dimensions": {"technical": {"data_coverage": 1.0}},
            }
        )
        titles = {f.title for f in check_confidence(report, TODAY)}
        assert "Low score confidence" in titles
        assert "Thin data coverage" in titles

    def test_thin_dimension_coverage_flagged(self):
        dims = {
            "technical": {"data_coverage": 1.0},
            "fundamental": {"data_coverage": 0.5},
            "risk": {"data_coverage": 1.0},
            "valuation": {"data_coverage": 0.83},
        }
        report = make_report(scoring={"confidence": "High", "dimensions": dims})
        [flag] = check_confidence(report, TODAY)
        assert "fundamental 50%" in flag.detail

    def test_full_coverage_passes(self):
        assert check_confidence(make_report(), TODAY) == []


class TestFreshnessAndCurrency:
    def test_each_freshness_warning_becomes_a_flag(self):
        report = make_report(warnings=["prices data is 9 days old", "info data is 3 days old"])
        assert len(check_freshness(report, TODAY)) == 2

    def test_unconverted_currency_mismatch(self):
        report = make_report(info={"currency": "NOK", "financial_currency": "USD"})
        [flag] = check_currency_mismatch(report, TODAY)
        assert "NOK" in flag.detail and "USD" in flag.detail

    def test_converted_statements_pass(self):
        report = make_report(info={"currency": "NOK", "financial_currency": "USD"})
        report["currency_conversion"] = {"from": "USD", "to": "NOK", "rate": 10.0}
        assert check_currency_mismatch(report, TODAY) == []

    def test_pence_listing_is_a_mismatch(self):
        report = make_report(info={"currency": "GBp", "financial_currency": "GBP"})
        assert len(check_currency_mismatch(report, TODAY)) == 1

    def test_same_currency_passes(self):
        report = make_report(info={"currency": "USD", "financial_currency": "USD"})
        assert check_currency_mismatch(report, TODAY) == []


def test_find_red_flags_sorts_by_severity():
    report = make_report(
        quality={"altman_z": 1.0},
        history={"interest_coverage": [1.5]},
        scoring={"confidence": "High", "dimensions": {"technical": {"data_coverage": 1.0}}},
    )
    flags = find_red_flags(report, TODAY)
    assert [f.severity for f in flags] == ["high", "medium", "low"]


def test_clean_report_has_no_flags():
    report = make_report(
        quality={"altman_z": 5.0, "beneish_m": {"m_score": -2.8, "components_available": 8}},
        history={
            "periods": ["2025-12-31", "2024-12-31", "2023-12-31"],
            "free_cash_flow": [10.0, 9.0, 8.0],
            "shares_outstanding": [100.0, 100.0, 100.0],
            "interest_coverage": [12.0],
        },
    )
    assert find_red_flags(report, TODAY) == []


# ============================================================
# Peer maths
# ============================================================


class TestPercentileRank:
    def test_between_values(self):
        assert percentile_rank(25, [10, 20, 30, 40]) == 50

    def test_ties_count_half(self):
        assert percentile_rank(20, [10, 20, 30, 40]) == pytest.approx(37.5)

    def test_extremes(self):
        assert percentile_rank(5, [10, 20, 30]) == 0
        assert percentile_rank(50, [10, 20, 30]) == 100

    def test_empty_population(self):
        assert percentile_rank(5, []) is None


class TestCompareToPeers:
    PEERS: ClassVar[dict[str, dict[str, float]]] = {
        "A": {"pe_ratio": 10, "price_to_book": 1.0, "free_cashflow": 5, "market_cap": 100},
        "B": {"pe_ratio": 20, "price_to_book": 2.0, "free_cashflow": 3, "market_cap": 100},
        "C": {"pe_ratio": 30, "price_to_book": 3.0, "free_cashflow": 1, "market_cap": 100},
        "D": {"pe_ratio": 40, "price_to_book": -1.0, "free_cashflow": 2, "market_cap": 100},
    }

    def test_median_percentile_and_cheapness(self):
        target = {"pe_ratio": 15, "price_to_book": 2.5, "free_cashflow": 4, "market_cap": 100}
        result = compare_to_peers("T", target, self.PEERS, basis="explicit")

        pe = result.metrics["pe_ratio"]
        assert pe.median == 25
        assert pe.percentile == 25  # one of four peers below 15
        assert pe.cheapness == 75  # lower P/E is cheaper
        assert pe.n == 4

    def test_negative_multiples_are_excluded(self):
        target = {"price_to_book": 2.5}
        pb = compare_to_peers("T", target, self.PEERS, basis="explicit").metrics["price_to_book"]
        assert pb.n == 3
        assert pb.median == 2.0

    def test_fcf_yield_higher_is_cheaper(self):
        target = {"free_cashflow": 4, "market_cap": 100}  # 4% yield
        fcf = compare_to_peers("T", target, self.PEERS, basis="explicit").metrics["fcf_yield"]
        assert fcf.median == pytest.approx(2.5)
        assert fcf.cheapness == 75  # yields more than three of four peers

    def test_fcf_yield_needs_matching_currency(self):
        info = {
            "free_cashflow": 5,
            "market_cap": 100,
            "currency": "NOK",
            "financial_currency": "USD",
        }
        assert metric_value(info, "fcf_yield") is None

    def test_missing_target_value(self):
        result = compare_to_peers("T", {}, self.PEERS, basis="explicit")
        assert result.metrics["pe_ratio"].percentile is None
        assert result.metrics["pe_ratio"].median == 25


class TestExplicitPeers:
    def test_explicit_peers_record_missing(self):
        infos = {"A": {"pe_ratio": 10}}
        result = peer_valuation(
            "T", {"pe_ratio": 12}, fetch_info=lambda t: infos.get(t, {}), peers=["A", "ZZZ"]
        )
        assert result.basis == "explicit"
        assert result.peers == ["A"]
        assert result.missing == ["ZZZ"]


# ============================================================
# Peer-relative scoring
# ============================================================


def _peer_context(median, n):
    return {"metrics": {"pe_ratio": {"median": median, "n": n}}}


class TestPeerRelativePE:
    def _pe_score(self, pe, peer_valuation=None, config=None):
        scorer = ValuationScorer(config)
        result = scorer.score({}, {"pe_ratio": pe}, peer_valuation)
        return next(s for s in result.sub_scores if s.name == "P/E Ratio")

    def test_absolute_cutoffs_without_peers(self):
        sub = self._pe_score(20.0)
        assert sub.score == pytest.approx(65.0)  # halfway between 15 and 25
        assert "peers" not in sub.label

    def test_peer_median_is_fair_value(self):
        sub = self._pe_score(40.0, _peer_context(40.0, 6))
        assert sub.score == pytest.approx(50.0)
        assert "vs peers" in sub.label

    def test_cheap_vs_expensive_peers(self):
        # P/E 30 is "Expensive" in absolute terms but cheap against a 60x peer group
        absolute = self._pe_score(30.0)
        relative = self._pe_score(30.0, _peer_context(60.0, 5))
        assert absolute.score < 50 < relative.score

    def test_too_few_peers_uses_absolute(self):
        assert self._pe_score(20.0, _peer_context(40.0, 3)).score == pytest.approx(65.0)

    def test_option_can_be_disabled(self):
        config = ScoringConfig()
        config.valuation.peer_relative = False
        assert self._pe_score(20.0, _peer_context(40.0, 8), config).score == pytest.approx(65.0)

    def test_stock_scorer_reads_peer_valuation_from_report(self):
        report = {"ticker": "T", "info": {"pe_ratio": 40.0}, "valuation_analysis": {"x": 1}}
        base = StockScorer().score(report).valuation.score
        report["peer_valuation"] = _peer_context(80.0, 5)
        assert StockScorer().score(report).valuation.score > base


# ============================================================
# 13F fund activity
# ============================================================


def _write_fund(tmp_path, cik, name, holdings):
    folder = tmp_path / "_discovery" / "edgar_13f"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{cik}.json").write_text(
        json.dumps(
            {
                "name": name,
                "cik": cik,
                "filing_date": "2026-08-14T00:00:00",
                "period_of_report": "2026-06-30T00:00:00",
                "holdings": holdings,
            }
        )
    )


def _holding(cusip, name, action, shares=100.0):
    return {"ticker": cusip, "name": name, "shares": shares, "value": shares * 10, "action": action}


class TestFundActivity:
    def test_no_cache_gives_hint(self, tmp_path):
        result = fund_activity("AAPL", "Apple Inc.", data_dir=str(tmp_path))
        assert not result.cache_found
        assert "quant discover" in result.hint

    def test_matches_by_cusip_map_and_name(self, tmp_path):
        _write_fund(tmp_path, "1", "Fund One", [_holding("037833100", "APPLE INC", "add")])
        _write_fund(tmp_path, "2", "Fund Two", [_holding("999999999", "APPLE INC", "new")])
        _write_fund(tmp_path, "3", "Fund Three", [_holding("111111111", "MICROSOFT CORP", "add")])
        enrichment = tmp_path / "_discovery" / "enrichment"
        enrichment.mkdir(parents=True)
        (enrichment / "cusip_map.json").write_text(json.dumps({"037833100": "AAPL"}))

        result = fund_activity("AAPL", "Apple Inc.", data_dir=str(tmp_path))

        assert result.funds_checked == 3
        by_fund = {p.fund: p for p in result.positions}
        assert set(by_fund) == {"Fund One", "Fund Two"}
        assert by_fund["Fund One"].matched_on == "ticker"
        assert by_fund["Fund Two"].matched_on == "name"
        assert result.positions[0].action == "new"  # most significant action first

    def test_share_classes_are_combined(self, tmp_path):
        _write_fund(
            tmp_path,
            "1",
            "Fund",
            [
                _holding("A1", "ALPHABET INC", "hold", 100),
                _holding("C1", "ALPHABET INC CL C", "add", 50),
            ],
        )
        [position] = fund_activity("GOOGL", "Alphabet Inc.", str(tmp_path)).positions
        assert position.shares == 150
        assert position.action == "add"

    def test_foreign_ticker_does_not_match_us_symbol(self, tmp_path):
        # DNB.OL (the Norwegian bank) is not DNB (Dun & Bradstreet)
        _write_fund(tmp_path, "1", "Fund", [_holding("DNB", "DUN & BRADSTREET HOLDINGS", "add")])
        assert fund_activity("DNB.OL", "DNB Bank ASA", str(tmp_path)).positions == []


# ============================================================
# Verdict helpers
# ============================================================


def _valuation_report(pe=30.0, premium=50.0):
    return {
        "ticker": "T",
        "info": {"pe_ratio": pe, "current_price": 100.0, "currency": "USD"},
        "valuation_analysis": {
            "dcf_valuation": {"discount_premium_pct": premium, "intrinsic_value_per_share": 66.7},
            "monte_carlo_valuation": {
                "confidence_intervals": {
                    "ci_10": 50,
                    "ci_25": 60,
                    "ci_50": 80,
                    "ci_75": 100,
                    "ci_90": 120,
                },
                "probability_undervalued": 0.3,
            },
        },
    }


class TestVerdict:
    def test_reprice_scales_multiples_and_dcf_premium(self):
        repriced = reprice_report(_valuation_report(pe=30.0, premium=50.0), 0.5)
        assert repriced["info"]["pe_ratio"] == 15.0
        # price 150% of intrinsic -> halve the price -> 75% of intrinsic
        assert repriced["valuation_analysis"]["dcf_valuation"][
            "discount_premium_pct"
        ] == pytest.approx(-25.0)

    def test_reprice_does_not_mutate_original(self):
        report = _valuation_report()
        reprice_report(report, 0.5)
        assert report["info"]["pe_ratio"] == 30.0
        assert report["valuation_analysis"]["dcf_valuation"]["discount_premium_pct"] == 50.0

    def test_fair_value_range(self):
        fv = fair_value_range(_valuation_report())
        assert fv["monte_carlo"]["ci_50"] == 80
        assert fv["upside_pct"]["mc_median"] == pytest.approx(-20.0)
        assert fv["dcf"] == 66.7

    def test_flip_prices_bracket_the_current_price(self):
        report = _valuation_report()
        flips = signal_flip_prices(report)
        current = SIGNAL_BANDS.index(flips["current_signal"])
        up, down = flips.get("up"), flips.get("down")

        assert up and up["price"] is not None and up["price"] < 100
        assert SIGNAL_BANDS.index(up["signal"]) == current + 1
        assert down and down["price"] is not None and down["price"] > 100

        # Just past each boundary the signal really has changed
        scorer = StockScorer()

        def signal_at(price):
            repriced = reprice_report(report, price / 100)
            return scorer.score_from_analyses(
                valuation_data=repriced["valuation_analysis"], ticker_info=repriced["info"]
            ).signal

        assert signal_at(up["price"] * 0.999) == up["signal"]
        assert signal_at(down["price"] * 1.001) == down["signal"]


# ============================================================
# Fundamentals history and signals
# ============================================================


def _statements():
    dates = ["2025-12-31", "2024-12-31", "2023-12-31"]
    cash_flow = pd.DataFrame(
        {
            d: {"Free Cash Flow": fcf, "Cash Dividends Paid": -40.0}
            for d, fcf in zip(dates, [-10.0, 50.0, -5.0], strict=True)
        }
    )
    income = pd.DataFrame(
        {d: {"EBIT": 30.0, "Interest Expense": 20.0, "Total Revenue": 1000.0} for d in dates}
    )
    balance = pd.DataFrame(
        {
            d: {"Ordinary Shares Number": s}
            for d, s in zip(dates, [121.0, 110.0, 100.0], strict=True)
        }
    )
    return {
        "cash_flow_annual": cash_flow,
        "income_stmt_annual": income,
        "balance_sheet_annual": balance,
    }


def test_annual_history_feeds_red_flags():
    history = FundamentalAnalyzer({}, _statements()).calculate_annual_history()

    assert history["periods"][0] == "2025-12-31"
    assert history["free_cash_flow"] == [-10.0, 50.0, -5.0]
    assert history["interest_coverage"][0] == pytest.approx(1.5)

    report = make_report(history=history)
    rules = {f.rule for f in find_red_flags(report, TODAY)}
    assert {"negative_fcf", "dilution", "interest_coverage"} <= rules


def test_pead_uses_most_recent_quarter_even_when_given_oldest_first():
    history = [
        {"quarter": "2025-12-31", "epsActual": 1.0, "epsEstimate": 1.2, "epsDifference": -0.2},
        {"quarter": "2026-03-31", "epsActual": 1.1, "epsEstimate": 1.2, "epsDifference": -0.1},
        {"quarter": "2026-06-30", "epsActual": 1.5, "epsEstimate": 1.2, "epsDifference": 0.3},
    ]
    result = calculate_pead_signal(history)
    assert result["earnings_date"] == "2026-06-30"
    assert result["streak_direction"] == "beat"


def test_pead_drift_with_tz_aware_prices(price_factory):
    prices = price_factory("AAPL", days=120)
    announced = prices.index[-30].tz_convert("UTC").isoformat()
    history = [
        {"quarter": announced, "epsActual": 1.5, "epsEstimate": 1.2, "epsDifference": 0.3},
        {"quarter": "2025-12-31", "epsActual": 1.0, "epsEstimate": 1.2, "epsDifference": -0.2},
    ]
    result = calculate_pead_signal(history, prices)
    assert result["days_since_earnings"] == 30
    assert result["drift_confirmed"] is not None


def test_pead_history_prefers_announcement_dates():
    earnings = {
        "earnings_dates": pd.DataFrame(
            {
                "Earnings Date": [
                    "2026-10-28 10:00:00-04:00",
                    "2026-07-21 20:00:00-04:00",
                    "2026-05-05",
                ],
                "EPS Estimate": [1.3, 1.38, 1.01],
                "Reported EPS": [None, 1.33, 1.48],
            }
        ),
        "earnings_history": pd.DataFrame(),
    }
    rows = pead_history(earnings)
    assert len(rows) == 2  # the future date has no reported EPS
    assert rows[0]["epsDifference"] == pytest.approx(-0.05)


# ============================================================
# End to end (offline fake market)
# ============================================================


@pytest.fixture
def vet_market(fake_market, tmp_path):
    """Target plus four same-industry peers on Yahoo's industry list."""
    fake_market.industries["software"] = ["AAPL", "MSFT", "ORCL", "ADBE", "CRM"]
    fake_market.info_overrides.update(
        {
            "AAPL": {"trailingPE": 30.0, "financialCurrency": "USD", "industryKey": "software"},
            "MSFT": {"trailingPE": 35.0},
            "ORCL": {"trailingPE": 40.0},
            "ADBE": {"trailingPE": 45.0},
            "CRM": {"trailingPE": 50.0},
            "XOM": {"industry": "Oil & Gas", "sector": "Energy", "trailingPE": 10.0},
        }
    )
    return fake_market, tmp_path


SECTION_TITLES = [
    "VET: AAPL",
    "RED FLAGS",
    "PEER VALUATION",
    "SIGNALS",
    "FUND ACTIVITY (13F)",
    "WHAT WOULD CHANGE THE VERDICT",
    "STRENGTHS / CONCERNS",
    "NEXT STEPS",
]


class TestVetEndToEnd:
    def test_pipeline_adds_relative_strength(self, fake_market, tmp_path):
        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)))
        rs = bundle.report["signals"]["relative_strength"]
        assert 1 <= rs["rs_rating"] <= 99
        assert rs["benchmark"] == "^GSPC"

    def test_vet_uses_yahoo_industry_peers(self, vet_market):
        _, tmp_path = vet_market
        result = vet_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), data_dir=str(tmp_path))

        assert result.peers.basis == "yahoo_industry"
        assert set(result.peers.peers) == {"MSFT", "ORCL", "ADBE", "CRM"}
        assert result.peers.metrics["pe_ratio"].median == 42.5
        pe_sub = next(
            s for s in result.bundle.scoring.valuation.sub_scores if s.name == "P/E Ratio"
        )
        assert "vs peers" in pe_sub.label
        assert result.report["scoring"]["composite_score"] == pytest.approx(
            result.bundle.scoring.composite_score, abs=0.1
        )

    def test_vet_writes_no_report_files(self, vet_market):
        _, tmp_path = vet_market
        vet_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), data_dir=str(tmp_path))
        assert not (tmp_path / "AAPL" / "reports").exists()

    def test_render_has_every_section_in_order(self, vet_market):
        _, tmp_path = vet_market
        result = vet_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), data_dir=str(tmp_path))

        text = render_text(result.to_dict())
        positions = [text.index(title) for title in SECTION_TITLES]
        assert positions == sorted(positions)
        assert "quant discover" in text  # no 13F cache in tmp_path

        markdown = render_markdown(result.to_dict())
        assert markdown.startswith("# VET: AAPL")
        assert "| Metric |" in markdown

    def test_explicit_peers_are_fetched(self, vet_market):
        market, tmp_path = vet_market
        result = vet_ticker(
            "AAPL",
            DataFetcher(cache_dir=str(tmp_path)),
            options=AnalysisOptions(include_context=False),
            peers=["NVDA", "MSFT"],
            data_dir=str(tmp_path),
        )
        assert result.peers.basis == "explicit"
        assert result.peers.peers == ["NVDA", "MSFT"]
        assert market.calls[("info", "NVDA")] == 1

    def test_cli_vet_json(self, vet_market):
        _, tmp_path = vet_market
        out = CliRunner().invoke(cli, ["--output-dir", str(tmp_path), "vet", "AAPL", "--json"])

        assert out.exit_code == 0, out.output
        data = json.loads(out.output)
        assert data["ticker"] == "AAPL"
        assert data["peer_valuation"]["basis"] == "yahoo_industry"
        assert "red_flags" in data and "signal_flips" in data

    def test_cli_vet_save(self, vet_market):
        _, tmp_path = vet_market
        out = CliRunner().invoke(
            cli, ["--output-dir", str(tmp_path), "vet", "AAPL", "--peers", "MSFT,ORCL", "--save"]
        )

        assert out.exit_code == 0, out.output
        assert "PEER VALUATION" in out.output
        reports = tmp_path / "AAPL" / "reports"
        assert (
            json.loads((reports / "vet.json").read_text())["peer_valuation"]["basis"] == "explicit"
        )
        assert (reports / "vet.md").read_text().startswith("# VET: AAPL")


# ============================================================
# Chat context
# ============================================================


def test_chat_context_includes_red_flags_and_peers():
    from src.llm import build_brief_context

    report = make_report(quality={"altman_z": 1.1}, info={"pe_ratio": 30.0})
    report["signals"] = {"relative_strength": {"rs_rating": 72, "benchmark": "^GSPC"}}
    peers = compare_to_peers(
        "TEST",
        {"pe_ratio": 30.0},
        {"A": {"pe_ratio": 20.0}, "B": {"pe_ratio": 40.0}},
        basis="yahoo_industry",
        group="Software",
    ).to_dict()

    context = build_brief_context(report, peer_valuation=peers)

    assert "=== RED FLAGS ===" in context
    assert "Altman Z-Score in distress zone" in context
    assert "PEER VALUATION (yahoo_industry in Software: A, B)" in context
    assert "P/E: 30.0 vs peer median 30.0" in context
    assert "Relative strength vs ^GSPC: 72/99" in context


def test_chat_context_without_flags_says_so():
    from src.llm import build_brief_context

    context = build_brief_context(make_report(), red_flags=[])
    assert "=== RED FLAGS ===\n  None found" in context


# ============================================================
# Verdict summary
# ============================================================


def _vet_data(signal="Hold", confidence="High", flags=(), cheapness=(), rs=None, actions=()):
    from src.vetting.vet import summarize_verdict

    data = {
        "header": {"signal": signal, "score": 60.0, "confidence": confidence},
        "red_flags": [{"severity": sev, "title": f"Flag {sev}"} for sev in flags],
        "peer_valuation": {
            "peers": ["A", "B", "C", "D"],
            "metrics": {f"m{i}": {"cheapness": c} for i, c in enumerate(cheapness)},
        },
        "signals": {"relative_strength": {"rs_rating": rs}} if rs is not None else {},
        "fund_activity": {"positions": [{"action": a} for a in actions]},
        "signal_flips": {"up": {"signal": "Buy", "price": 90.0, "change_pct": -10.0}},
    }
    return summarize_verdict(data)


class TestVerdictSummary:
    def test_buy_with_confidence_is_look_deeper(self):
        assert _vet_data(signal="Buy")["call"] == "Look deeper"

    def test_buy_with_low_confidence_is_watch(self):
        assert _vet_data(signal="Buy", confidence="Low")["call"] == "Watch"

    def test_high_red_flag_is_pass_even_on_buy(self):
        verdict = _vet_data(signal="Strong Buy", flags=("high", "low"))
        assert verdict["call"] == "Pass"
        assert "red flag: flag high" in verdict["reasons"]

    def test_sell_is_pass(self):
        assert _vet_data(signal="Sell")["call"] == "Pass"

    def test_hold_is_watch(self):
        assert _vet_data()["call"] == "Watch"

    def test_reasons_summarize_peers_momentum_and_funds(self):
        verdict = _vet_data(cheapness=(80, 70, 90), rs=85, actions=("new", "add", "trim"))
        assert "cheap vs 4 peers" in verdict["reasons"]
        assert "strong momentum (RS 85)" in verdict["reasons"]
        assert "tracked funds: 2 buying, 1 selling" in verdict["reasons"]
        assert verdict["flip"]["signal"] == "Buy"

    def test_expensive_vs_peers(self):
        assert "expensive vs 4 peers" in _vet_data(cheapness=(10, 20))["reasons"]


def test_brief_render_is_verdict_and_next_steps(vet_market):
    _, tmp_path = vet_market
    data = vet_ticker(
        "AAPL", DataFetcher(cache_dir=str(tmp_path)), data_dir=str(tmp_path)
    ).to_dict()

    brief = render_text(data, brief=True)
    full = render_text(data)

    assert "VERDICT:" in brief and "NEXT STEPS" in brief
    assert "PEER VALUATION" not in brief
    assert full.index("VERDICT:") < full.index("RED FLAGS")
