"""
Tests for the Phase 2b data sources: statement currency conversion, Yahoo
industry peers, and analyst price targets. All offline via `fake_market`.
"""

from typing import ClassVar, List

import pandas as pd
import pytest

from src.data_fetcher import DataFetcher
from src.pipeline import AnalysisOptions, analyze_ticker
from src.utils.fx import (
    adjust_info_ratios,
    conversion_rate,
    convert_statements,
    fx_symbol,
    major_currency,
    normalize_info,
    usd_per_unit,
)
from src.vetting import (
    fair_value_range,
    find_red_flags,
    peer_valuation,
    render_text,
    vet_ticker,
)
from src.vetting.peers import metric_value
from src.vetting.vet import summarize_verdict

# ============================================================
# FX helpers
# ============================================================


class TestFxHelpers:
    def test_major_currency(self):
        assert major_currency("GBp") == ("GBP", 100.0)
        assert major_currency("usd") == ("USD", 1.0)

    def test_fx_symbol(self):
        assert fx_symbol("usd", "nok") == "USDNOK=X"

    def test_rate_from_lookup(self):
        rate, symbol = conversion_rate("USD", "NOK", lambda s: 10.5 if s == "USDNOK=X" else None)
        assert rate == 10.5
        assert symbol == "USDNOK=X"

    def test_pounds_to_pence_needs_no_lookup(self):
        rate, symbol = conversion_rate("GBP", "GBp", lambda s: None)
        assert rate == 100.0
        assert symbol is None

    def test_dollars_to_pence(self):
        rate, _ = conversion_rate("USD", "GBp", lambda s: 0.8)
        assert rate == pytest.approx(80.0)

    def test_missing_rate(self):
        assert conversion_rate("USD", "NOK", lambda s: None) is None

    def test_convert_statements_scales_money_not_counts(self):
        frame = pd.DataFrame(
            {"2025-12-31": [100.0, 5.0, 1000.0, 0.21, 2.5]},
            index=[
                "Free Cash Flow",
                "Diluted EPS",
                "Ordinary Shares Number",
                "Tax Rate For Calcs",
                "Diluted Average Shares",
            ],
        )
        converted = convert_statements({"cash_flow_annual": frame}, 10.0)["cash_flow_annual"]
        col = converted["2025-12-31"]
        assert col["Free Cash Flow"] == 1000.0
        assert col["Diluted EPS"] == 50.0
        assert col["Ordinary Shares Number"] == 1000.0
        assert col["Tax Rate For Calcs"] == 0.21
        assert col["Diluted Average Shares"] == 2.5
        assert frame.loc["Free Cash Flow", "2025-12-31"] == 100.0  # original untouched


# ============================================================
# Pipeline conversion
# ============================================================


def _usd_statements():
    dates = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    cashflow = pd.DataFrame(
        {d: {"Free Cash Flow": 5e9, "Cash Dividends Paid": -2e9} for d in dates}
    )
    income = pd.DataFrame(
        {d: {"Total Revenue": 100e9, "EBIT": 20e9, "Interest Expense": 1e9} for d in dates}
    )
    balance = pd.DataFrame(
        {d: {"Ordinary Shares Number": 2.5e9, "Common Stock Equity": 40e9} for d in dates}
    )
    return {"cashflow": cashflow, "income_stmt": income, "balance_sheet": balance}


@pytest.fixture
def usd_reporter(fake_market):
    """EQNR.OL: trades in NOK (market cap 1T NOK), reports in USD; USDNOK = 10."""
    fake_market.info_overrides["EQNR.OL"] = {
        "financialCurrency": "USD",
        "marketCap": 1_000_000_000_000,
    }
    fake_market.attribute_overrides["EQNR.OL"] = _usd_statements()
    fx = fake_market.ticker("X").history()  # any frame shape; override prices below
    fake_market.price_overrides["USDNOK=X"] = fx.assign(Close=10.0, Open=10.0, High=10.0, Low=10.0)
    return fake_market


class TestStatementConversion:
    def test_statements_converted_to_listing_currency(self, usd_reporter, tmp_path):
        bundle = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.report["currency_conversion"] == {
            "from": "USD",
            "to": "NOK",
            "rate": 10.0,
            "fx_symbol": "USDNOK=X",
        }
        fcf = bundle.report["fundamental_analysis"]["analysis"]["fcf_metrics"]
        assert fcf["fcf"] == pytest.approx(50e9)
        assert fcf["fcf_yield"] == pytest.approx(5.0)  # 50B NOK / 1T NOK
        history = bundle.report["fundamental_analysis"]["analysis"]["annual_history"]
        assert history["shares_outstanding"][0] == 2.5e9  # counts are not scaled
        assert history["interest_coverage"][0] == pytest.approx(20.0)  # ratios unchanged

    def test_cache_keeps_original_currency(self, usd_reporter, tmp_path):
        fetcher = DataFetcher(cache_dir=str(tmp_path))
        analyze_ticker("EQNR.OL", fetcher)

        raw = fetcher.fetch_fundamentals("EQNR.OL")["cash_flow_annual"]
        assert raw.loc["Free Cash Flow"].iloc[0] == 5e9

    def test_no_conversion_for_same_currency(self, fake_market, tmp_path):
        fake_market.info_overrides["AAPL"] = {"financialCurrency": "USD"}
        bundle = analyze_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)))
        assert "currency_conversion" not in bundle.report

    def test_missing_fx_rate_is_flagged(self, usd_reporter, tmp_path):
        usd_reporter.failing.add("USDNOK=X")

        bundle = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.report["currency_conversion"]["rate"] is None
        fcf = bundle.report["fundamental_analysis"]["analysis"]["fcf_metrics"]
        assert fcf["fcf"] == pytest.approx(5e9)
        rules = {f.rule for f in find_red_flags(bundle.report)}
        assert "currency_mismatch" in rules

    def test_converted_report_has_no_currency_flag(self, usd_reporter, tmp_path):
        bundle = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path)))
        assert "currency_mismatch" not in {f.rule for f in find_red_flags(bundle.report)}
        assert "converted USD -> NOK" in fair_value_range(bundle.report)["currency_note"]


# ============================================================
# Yahoo industry peers
# ============================================================


class TestIndustryPeers:
    def test_fetch_and_cache(self, fake_market, tmp_path):
        fake_market.industries["software"] = ["MSFT", "ORCL"]
        fetcher = DataFetcher(cache_dir=str(tmp_path))

        assert fetcher.get_industry_peers("software") == ["MSFT", "ORCL"]
        assert fetcher.get_industry_peers("software") == ["MSFT", "ORCL"]
        assert fake_market.calls[("industry", "software")] == 1

    def test_stale_cache_on_failure(self, fake_market, tmp_path):
        fake_market.industries["software"] = ["MSFT"]
        DataFetcher(cache_dir=str(tmp_path)).get_industry_peers("software")
        fake_market.failing.add("software")

        peers = DataFetcher(cache_dir=str(tmp_path)).get_industry_peers("software", use_cache=False)

        assert peers == ["MSFT"]

    def test_failure_without_cache(self, fake_market, tmp_path):
        fake_market.failing.add("software")
        assert DataFetcher(cache_dir=str(tmp_path)).get_industry_peers("software") == []


def _infos(*tickers, **fields):
    return {t: {"name": f"{t} Corp", "pe_ratio": 20.0, **fields} for t in tickers}


class TestPeerSourceChoice:
    YAHOO: ClassVar[List[str]] = ["MSFT", "ORCL", "ADBE", "CRM", "NOW"]

    def _run(self, ticker, info, yahoo=None):
        infos = _infos(*(yahoo or self.YAHOO))
        return peer_valuation(
            ticker,
            info,
            fetch_info=lambda t: infos.get(t, {}),
            industry_peers=lambda key: list(infos),
        )

    def test_yahoo_industry_list(self):
        info = {"name": "Apple Inc.", "industry": "Software", "industry_key": "software"}

        result = self._run("AAPL", info)

        assert result.basis == "yahoo_industry"
        assert result.group == "Software"
        assert result.peers == self.YAHOO

    def test_explicit_peers_skip_yahoo_and_size_filter(self):
        infos = {"TINY.OL": {"name": "Tiny ASA", "market_cap": 1e6, "currency": "NOK"}}
        result = peer_valuation(
            "EQNR.OL",
            {"name": "Equinor ASA", "market_cap": 1e12, "industry_key": "oil"},
            fetch_info=lambda t: infos.get(t, {}),
            peers=["TINY.OL"],
            industry_peers=lambda key: pytest.fail("Yahoo list used despite --peers"),
        )
        assert result.basis == "explicit"
        assert result.peers == ["TINY.OL"]

    def test_yahoo_failure_gives_no_peers(self):
        def broken(key):
            raise RuntimeError("Yahoo down")

        result = peer_valuation(
            "AAPL",
            {"name": "Apple Inc.", "industry_key": "software", "sector_key": "technology"},
            fetch_info=lambda t: {},
            industry_peers=broken,
            sector_peers=broken,
        )
        assert result.basis == "none"
        assert result.peers == []

    def test_same_company_listings_are_dropped(self):
        info = {"name": "EQNR.OL Corp", "industry": "Oil", "industry_key": "oil"}
        result = self._run("EQNR.OL", info, yahoo=["EQNR.OL", "XOM", "CVX", "SHEL", "BP", "TTE"])
        assert "EQNR.OL" not in result.peers

        adr = {"name": "Equinor ASA", "industry": "Oil", "industry_key": "oil"}
        infos = {"EQNR": {"name": "Equinor ASA", "pe_ratio": 10.0}, **_infos("XOM")}
        result = peer_valuation(
            "EQNR.OL",
            adr,
            fetch_info=lambda t: infos.get(t, {}),
            industry_peers=lambda key: list(infos),
        )
        assert result.peers == ["XOM"]

    def test_vet_uses_yahoo_industry_end_to_end(self, fake_market, tmp_path):
        fake_market.info_overrides["AAPL"] = {"industryKey": "software"}
        fake_market.industries["software"] = ["AAPL", "MSFT", "ORCL", "ADBE", "CRM"]

        result = vet_ticker("AAPL", DataFetcher(cache_dir=str(tmp_path)), data_dir=str(tmp_path))

        assert result.peers.basis == "yahoo_industry"
        assert result.peers.peers == ["MSFT", "ORCL", "ADBE", "CRM"]


# ============================================================
# Analyst targets
# ============================================================


def _report_with_targets(**info):
    return {
        "ticker": "T",
        "info": {"current_price": 100.0, "currency": "USD", **info},
        "valuation_analysis": {},
    }


class TestAnalystTargets:
    def test_fair_value_includes_targets(self):
        fv = fair_value_range(
            _report_with_targets(
                target_mean_price=120.0,
                target_low_price=90.0,
                target_high_price=150.0,
                analyst_count=12,
                recommendation_key="buy",
            )
        )
        assert fv["analysts"]["mean"] == 120.0
        assert fv["analysts"]["count"] == 12
        assert fv["upside_pct"]["analyst_mean"] == pytest.approx(20.0)

    def test_no_targets(self):
        assert "analysts" not in fair_value_range(_report_with_targets())

    def test_verdict_mentions_targets_with_enough_analysts(self):
        data = {
            "header": {"signal": "Hold", "score": 55.0, "confidence": "High"},
            "fair_value": {
                "analysts": {"mean": 120.0, "count": 12},
                "upside_pct": {"analyst_mean": 20.0},
            },
        }
        assert "analyst target +20%" in summarize_verdict(data)["reasons"]

        data["fair_value"]["analysts"]["count"] = 2
        assert not any("analyst" in r for r in summarize_verdict(data)["reasons"])

    def test_targets_flow_from_yahoo_info(self, fake_market, tmp_path):
        fake_market.info_overrides["AAPL"] = {
            "targetMeanPrice": 250.0,
            "numberOfAnalystOpinions": 30,
            "recommendationKey": "buy",
        }
        result = vet_ticker(
            "AAPL",
            DataFetcher(cache_dir=str(tmp_path)),
            options=AnalysisOptions(include_context=False),
            data_dir=str(tmp_path),
        )
        assert result.fair_value["analysts"]["mean"] == 250.0


# ============================================================
# Yahoo's mixed-currency ratios
# ============================================================

EQNR_INFO = {  # Yahoo's numbers for EQNR.OL (NOK listing, USD statements)
    "currency": "NOK",
    "financial_currency": "USD",
    "market_cap": 959_360_139_264,
    "enterprise_value": 992_587_677_696,
    "ev_to_ebitda": 23.704,
    "price_to_sales": 8.4411335,
    "free_cashflow": 29_396_250_624,
    "pe_ratio": 11.56,
}


class TestYahooRatioCorrection:
    def test_adjust_info_ratios(self):
        adjusted = adjust_info_ratios(EQNR_INFO, 9.522)

        assert adjusted["price_to_sales"] == pytest.approx(0.886, abs=0.001)
        # EBITDA 41.9B USD, net debt 33.2B USD -> (959B + 316B NOK) / 399B NOK
        assert adjusted["ev_to_ebitda"] == pytest.approx(3.2, abs=0.05)
        assert adjusted["pe_ratio"] == 11.56  # Yahoo gets per-share ratios right
        assert adjusted["free_cashflow"] == EQNR_INFO["free_cashflow"]
        assert EQNR_INFO["price_to_sales"] == 8.4411335  # original untouched

    def test_uncorrected_mixed_ratios_are_skipped(self):
        assert metric_value(EQNR_INFO, "price_to_sales") is None
        assert metric_value(EQNR_INFO, "pe_ratio") == 11.56

    def test_corrected_ratios_are_used_except_fcf_yield(self):
        adjusted = adjust_info_ratios(EQNR_INFO, 9.522)
        assert metric_value(adjusted, "price_to_sales") == pytest.approx(0.886, abs=0.001)
        assert metric_value(adjusted, "fcf_yield") is None

    def test_unknown_statement_currency_on_foreign_listing(self):
        info = {"currency": "NOK", "price_to_sales": 3.0}  # cached before the field existed
        assert metric_value(info, "price_to_sales") is None
        assert metric_value({"currency": "USD", "price_to_sales": 3.0}, "price_to_sales") == 3.0

    def test_pipeline_corrects_target_ratios(self, usd_reporter, tmp_path):
        usd_reporter.info_overrides["EQNR.OL"]["priceToSalesTrailing12Months"] = 9.5
        bundle = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path)))

        assert bundle.report["info"]["price_to_sales"] == pytest.approx(0.95)
        cached = DataFetcher(cache_dir=str(tmp_path)).get_ticker_info("EQNR.OL")
        assert cached["price_to_sales"] == 9.5  # the cache keeps Yahoo's value

    def test_pipeline_computes_target_pb_from_converted_equity(self, usd_reporter, tmp_path):
        usd_reporter.info_overrides["EQNR.OL"]["priceToBook"] = 60.0  # Yahoo's mixed P/B
        info = analyze_ticker("EQNR.OL", DataFetcher(cache_dir=str(tmp_path))).report["info"]

        assert info["price_to_book"] == pytest.approx(2.5)  # 1T NOK / (40B USD * 10)
        assert "price_to_book" in info["converted_ratios"]
        assert metric_value(info, "price_to_book") == pytest.approx(2.5)

    def test_raw_peer_statement_ratios_are_skipped(self):
        info = {**EQNR_INFO, "price_to_book": 60.0}
        for key in ("price_to_sales", "ev_to_ebitda", "price_to_book", "fcf_yield"):
            assert metric_value(info, key) is None
        assert metric_value(info, "pe_ratio") == 11.56

    def test_normalized_peers_keep_converted_ratios_only(self):
        peer = normalize_info({**EQNR_INFO, "name": "Peer ASA"}, {"USDNOK=X": 9.522}.get)
        result = peer_valuation(
            "T.OL",
            {"name": "Target", "currency": "NOK", "financial_currency": "NOK"},
            fetch_info=lambda t: peer,
            peers=["P.OL"],
        )
        assert result.metrics["price_to_sales"].median == pytest.approx(0.886, abs=0.001)
        assert result.metrics["ev_to_ebitda"].median == pytest.approx(3.2, abs=0.05)
        assert result.metrics["price_to_book"].n == 0  # can't be converted from info alone
        assert result.metrics["fcf_yield"].n == 0

    def test_normalize_info_leaves_single_currency_and_missing_fx_alone(self):
        usd = {"currency": "USD", "financial_currency": "USD", "price_to_sales": 3.0}
        assert normalize_info(usd, {}.get) is usd
        assert normalize_info(EQNR_INFO, {}.get) is EQNR_INFO


class TestUsdPerUnit:
    def test_prefers_cached_inverse(self):
        rates = {"USDNOK=X": 10.0, "NOKUSD=X": 0.2}
        assert usd_per_unit("NOK", rates.get) == pytest.approx(0.1)

    def test_falls_back_to_direct_pair(self):
        assert usd_per_unit("NOK", {"NOKUSD=X": 0.1}.get) == pytest.approx(0.1)

    def test_minor_units(self):
        assert usd_per_unit("GBp", {"USDGBP=X": 0.8}.get) == pytest.approx(0.0125)

    def test_usd_and_unknown(self):
        assert usd_per_unit("USD", {}.get) == 1.0
        assert usd_per_unit("XYZ", {}.get) is None


# ============================================================
# Size-aware peer groups
# ============================================================


def _sized(caps):
    return {
        t: {"name": f"{t} Inc", "currency": "USD", "market_cap": cap, "pe_ratio": 20.0}
        for t, cap in caps.items()
    }


class TestSizeAwarePeers:
    TARGET = {
        "name": "Apple Inc.",
        "currency": "USD",
        "market_cap": 4e12,
        "industry": "Consumer Electronics",
        "industry_key": "consumer-electronics",
        "sector": "Technology",
        "sector_key": "technology",
    }

    def _run(self, industry, sector):
        infos = {**_sized(industry), **_sized(sector)}
        return peer_valuation(
            "AAPL",
            self.TARGET,
            fetch_info=lambda t: infos.get(t, {}),
            industry_peers=lambda key: list(industry),
            sector_peers=lambda key: list(sector),
        )

    def test_micro_caps_are_dropped_and_sector_used(self):
        industry = {"SONO": 1.5e9, "UEIC": 1e8, "AXIL": 5e7}
        sector = {"MSFT": 3.5e12, "NVDA": 4.5e12, "AVGO": 1.5e12, "ORCL": 8e11, "TINY": 1e9}

        result = self._run(industry, sector)

        assert result.basis == "yahoo_sector"
        assert set(result.peers) == {"MSFT", "NVDA", "AVGO", "ORCL"}
        assert result.peers[0] in ("MSFT", "NVDA")  # closest in size first

    def test_industry_used_when_enough_similar_size(self):
        industry = {"A": 2e12, "B": 3e12, "C": 5e12, "D": 1e12}
        result = self._run(industry, {"MSFT": 3.5e12})
        assert result.basis == "yahoo_industry"

    def test_foreign_cap_compared_in_usd(self):
        target = {**self.TARGET, "currency": "NOK", "market_cap": 1e12}  # ~100B USD
        industry = {"XOM": 5e11, "CVX": 3e11, "COP": 1.2e11, "HES": 5e10, "NFG": 6e9}
        infos = _sized(industry)
        result = peer_valuation(
            "EQNR.OL",
            target,
            fetch_info=lambda t: infos.get(t, {}),
            industry_peers=lambda key: list(industry),
            fx_lookup={"USDNOK=X": 10.0}.get,
        )
        assert result.basis == "yahoo_industry"
        assert "NFG" not in result.peers

    def test_short_industry_is_topped_up_from_sector(self):
        industry = {"XOM": 1.2e13, "CVX": 1.3e13}  # in the band, but furthest in size
        sector = {f"S{i}": 4e12 + i * 1e10 for i in range(12)}

        result = self._run(industry, sector)

        assert result.basis == "yahoo_industry_sector"
        assert result.peers[:2] == ["XOM", "CVX"]  # industry peers stay first
        assert len(result.peers) == 10

    def test_sector_adding_nothing_keeps_industry_basis(self):
        industry = {"A": 2e12, "B": 3e12}
        result = self._run(industry, {"A": 2e12})
        assert result.basis == "yahoo_industry"
        assert result.peers == ["B", "A"]

    def test_unknown_peer_currency_is_dropped_by_size_filter(self):
        industry = {"A": 2e12, "B": 3e12, "C": 5e12, "D": 1e12}
        infos = _sized(industry)
        infos["D"]["currency"] = "NOK"  # no FX lookup, so its USD size is unknown
        result = peer_valuation(
            "AAPL",
            self.TARGET,
            fetch_info=lambda t: infos.get(t, {}),
            industry_peers=lambda key: list(industry),
        )
        assert result.peers == ["C", "B", "A"]  # closest to 4T first

    def test_info_cached_before_new_fields_is_refetched(self, fake_market, tmp_path):
        (tmp_path / "AAPL" / "cache").mkdir(parents=True)
        (tmp_path / "AAPL" / "cache" / "info.json").write_text('{"name": "Apple Inc."}')

        info = DataFetcher(cache_dir=str(tmp_path)).get_ticker_info("AAPL")

        assert "financial_currency" in info
        assert fake_market.calls[("info", "AAPL")] == 1

    def test_sector_list_fetch_and_cache(self, fake_market, tmp_path):
        fake_market.sectors["technology"] = ["MSFT", "NVDA"]
        fetcher = DataFetcher(cache_dir=str(tmp_path))

        assert fetcher.get_sector_peers("technology") == ["MSFT", "NVDA"]
        assert fetcher.get_sector_peers("technology") == ["MSFT", "NVDA"]
        assert fake_market.calls[("sector", "technology")] == 1


# ============================================================
# Wording
# ============================================================


def test_pead_wording():
    data = {
        "signals": {
            "pead": {
                "signal": "slight_negative",
                "sue": -0.25,
                "streak": 1,
                "streak_direction": "miss",
                "interpretation": "Small miss",
            }
        }
    }
    text = render_text(data)
    assert "Post-earnings drift: slightly negative (SUE -0.25, 1 miss in a row)" in text

    data["signals"]["pead"].update(streak=14, streak_direction="beat", signal="buy")
    assert "positive (SUE -0.25, 14 beats in a row)" in render_text(data)
