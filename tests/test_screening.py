"""
Tests for universe resolution and the two-stage screener.
"""

import json

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import cli
from src.data_fetcher import DataFetcher
from src.pipeline import AnalysisOptions
from src.screening import (
    BUILTIN_INDEXES,
    Screener,
    ScreenFilters,
    parse_amount,
    resolve_universe,
    save_screen,
)
from src.screening.universe import IndexSource, load_index, load_ticker_file, parse_constituents

# Test-only index so parsing/caching tests don't depend on a real index's size
SMALL_INDEX = IndexSource(
    name="small",
    description="test index",
    url="https://example.test/index",
    column_candidates=("Symbol", "Ticker"),
    min_expected=25,
)


def _wiki_table(column: str, symbols: list[str]) -> str:
    rows = "".join(f"<tr><td>{s}</td><td>Co {s}</td></tr>" for s in symbols)
    return f"<table><tr><th>{column}</th><th>Security</th></tr>{rows}</table>"


# ============================================================
# Universe resolution
# ============================================================


class TestParseConstituents:
    def test_sp500_share_classes_become_yahoo_symbols(self):
        symbols = ["AAPL", "BRK.B", "BF.B"] + [f"T{i}" for i in range(400)]
        html = _wiki_table("Symbol", symbols)

        tickers = parse_constituents(html, BUILTIN_INDEXES["sp500"])

        assert tickers[:3] == ["AAPL", "BRK-B", "BF-B"]

    def test_oslo_symbols_get_exchange_suffix(self):
        html = _wiki_table("Ticker", ["EQNR", "DNB", "OSE: MOWI"] + [f"X{i}" for i in range(15)])

        tickers = parse_constituents(html, BUILTIN_INDEXES["obx"])

        assert tickers[:3] == ["EQNR.OL", "DNB.OL", "MOWI.OL"]

    def test_skips_tables_too_small_to_be_the_index(self):
        small = _wiki_table("Symbol", ["WRONG"])
        real = _wiki_table("Symbol", [f"T{i}" for i in range(30)])

        tickers = parse_constituents(small + real, SMALL_INDEX)

        assert "WRONG" not in tickers
        assert len(tickers) == 30

    def test_tolerates_footnotes_two_row_headers_and_exchange_prefixes(self):
        rows = "".join(f"<tr><td>Co {i}</td><td>NYSE: T{i}</td></tr>" for i in range(30))
        html = (
            "<table><thead><tr><th colspan='2'>Components</th></tr>"
            "<tr><th>Company</th><th>Symbol[a]</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

        tickers = parse_constituents(html, SMALL_INDEX)

        assert tickers[:2] == ["T0", "T1"]

    def test_error_lists_tables_seen(self):
        html = _wiki_table("Company", [f"T{i}" for i in range(30)])

        with pytest.raises(ValueError, match="30 rows: company"):
            parse_constituents(html, SMALL_INDEX)


class TestLoadIndex:
    def test_second_load_uses_cache(self, default_config, tmp_path):
        calls = []
        html = _wiki_table("Symbol", [f"T{i}" for i in range(30)])

        def fetch(url):
            calls.append(url)
            return html

        load_index(SMALL_INDEX, str(tmp_path), fetch_text=fetch)
        tickers = load_index(SMALL_INDEX, str(tmp_path), fetch_text=fetch)

        assert len(calls) == 1
        assert len(tickers) == 30

    def test_refresh_failure_falls_back_to_cached_list(self, default_config, tmp_path):
        html = _wiki_table("Symbol", [f"T{i}" for i in range(30)])
        load_index(SMALL_INDEX, str(tmp_path), fetch_text=lambda url: html)

        def offline(url):
            raise ConnectionError("offline")

        tickers = load_index(SMALL_INDEX, str(tmp_path), use_cache=False, fetch_text=offline)

        assert len(tickers) == 30

    def test_failure_without_cache_suggests_ticker_file(self, default_config, tmp_path):
        def offline(url):
            raise ConnectionError("offline")

        with pytest.raises(ValueError, match="ticker file"):
            load_index(SMALL_INDEX, str(tmp_path), fetch_text=offline)


def _nasdaq_payload(symbols: list[str]) -> str:
    rows = [{"symbol": s, "companyName": f"Co {s}"} for s in symbols]
    return json.dumps({"data": {"data": {"headers": {"symbol": "Symbol"}, "rows": rows}}})


class TestNasdaqSource:
    def test_nasdaq_api_is_tried_first(self, default_config, tmp_path):
        calls = []

        def fetch(url):
            calls.append(url)
            return _nasdaq_payload(["AAPL", "MSFT"] + [f"N{i}" for i in range(98)])

        tickers = load_index(BUILTIN_INDEXES["nasdaq100"], str(tmp_path), fetch_text=fetch)

        assert calls == ["https://api.nasdaq.com/api/quote/list-type/nasdaq100"]
        assert tickers[:2] == ["AAPL", "MSFT"]

    def test_falls_back_to_wikipedia_when_api_fails(self, default_config, tmp_path):
        def fetch(url):
            if "nasdaq.com" in url:
                raise ConnectionError("403 Forbidden")
            return _wiki_table("Ticker", [f"W{i}" for i in range(100)])

        tickers = load_index(BUILTIN_INDEXES["nasdaq100"], str(tmp_path), fetch_text=fetch)

        assert tickers[0] == "W0"

    def test_error_lists_every_failed_source(self, default_config, tmp_path):
        def fetch(url):
            raise ConnectionError(f"down: {url}")

        with pytest.raises(ValueError) as excinfo:
            load_index(BUILTIN_INDEXES["nasdaq100"], str(tmp_path), fetch_text=fetch)

        assert "api.nasdaq.com" in str(excinfo.value)
        assert "wikipedia.org" in str(excinfo.value)

    def test_share_class_slash_becomes_yahoo_dash(self, default_config, tmp_path):
        payload = _nasdaq_payload(["BRK/B"] + [f"N{i}" for i in range(99)])

        tickers = load_index(
            BUILTIN_INDEXES["nasdaq100"], str(tmp_path), fetch_text=lambda url: payload
        )

        assert tickers[0] == "BRK-B"


def test_wikipedia_tables_split_by_sector_are_combined():
    html = "".join(_wiki_table("Ticker", [f"{sector}{i}" for i in range(30)]) for sector in "ABCD")

    tickers = parse_constituents(html, BUILTIN_INDEXES["nasdaq100"])

    assert len(tickers) == 120


class TestResolveUniverse:
    def test_mixes_file_and_literal_tickers_without_duplicates(self, tmp_path):
        ticker_file = tmp_path / "mine.txt"
        ticker_file.write_text("# my picks\nAAPL, msft\nEQNR.OL  # oil\n", encoding="utf-8")

        universe = resolve_universe([str(ticker_file), "aapl", "NVDA"], data_dir=str(tmp_path))

        assert universe.tickers == ["AAPL", "MSFT", "EQNR.OL", "NVDA"]
        assert universe.label == "mine+tickers"

    def test_discover_skips_unresolved_cusips(self, tmp_path):
        discovery = tmp_path / "_discovery" / "discovery_result.json"
        discovery.parent.mkdir(parents=True)
        discovery.write_text(
            json.dumps(
                {
                    "overlap_signals": [
                        {"ticker": "AAPL"},
                        {"ticker": "037833100"},
                        {"ticker": "BRK.B"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        universe = resolve_universe(["discover"], data_dir=str(tmp_path))

        assert universe.tickers == ["AAPL", "BRK-B"]

    def test_discover_without_results_explains_next_step(self, tmp_path):
        with pytest.raises(ValueError, match="quant discover"):
            resolve_universe(["discover"], data_dir=str(tmp_path))


def test_ticker_file_csv_uses_symbol_column(tmp_path):
    csv_file = tmp_path / "export.csv"
    csv_file.write_text("Name,Symbol\nApple,aapl\nMicrosoft,MSFT\n", encoding="utf-8")

    assert load_ticker_file(csv_file) == ["AAPL", "MSFT"]


# ============================================================
# Filters and amount parsing
# ============================================================


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("750000", 750_000, id="plain"),
        pytest.param("500K", 500_000, id="thousands"),
        pytest.param("2.5b", 2.5e9, id="billions-lowercase"),
        pytest.param("1T", 1e12, id="trillions"),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_parse_amount_rejects_garbage():
    with pytest.raises(ValueError):
        parse_amount("lots")


class TestScreenFilters:
    INFO = {
        "sector": "Technology",
        "industry": "Semiconductors",
        "market_cap": 5e9,
        "avg_volume": 1e6,
    }

    @pytest.mark.parametrize(
        ("filters", "passes"),
        [
            pytest.param(ScreenFilters(), True, id="no-filters"),
            pytest.param(ScreenFilters(sectors=("tech",)), True, id="sector-substring"),
            pytest.param(ScreenFilters(sectors=("semicon",)), True, id="industry-substring"),
            pytest.param(ScreenFilters(sectors=("Energy",)), False, id="other-sector"),
            pytest.param(ScreenFilters(exclude_sectors=("Technology",)), False, id="excluded"),
            pytest.param(ScreenFilters(min_market_cap=10e9), False, id="too-small"),
            pytest.param(ScreenFilters(max_market_cap=1e9), False, id="too-large"),
            pytest.param(ScreenFilters(min_avg_volume=5e6), False, id="illiquid"),
        ],
    )
    def test_rejection(self, filters, passes):
        assert (filters.rejection_reason(self.INFO) is None) is passes

    def test_active_filter_rejects_missing_info(self):
        assert ScreenFilters(sectors=("Tech",)).rejection_reason({}) is not None


# ============================================================
# Screener
# ============================================================


@pytest.fixture
def screener(fake_market, tmp_path):
    return Screener(fetcher=DataFetcher(cache_dir=str(tmp_path)), options=AnalysisOptions())


class TestScreener:
    def test_ranks_everyone_and_scores_top_n(self, screener):
        result = screener.run(["AAA", "BBB", "CCC", "DDD", "EEE"], top_n=3)

        assert len(result.ranked) == 5
        assert len(result.scored) == 3
        assert all(c.scoring is not None for c in result.scored)

    def test_scored_candidates_sorted_by_composite_score(self, screener):
        result = screener.run(["AAA", "BBB", "CCC", "DDD"], top_n=4)

        scores = [c.scoring.composite_score for c in result.scored]
        assert scores == sorted(scores, reverse=True)

    def test_shortlist_is_best_factor_ranks(self, screener):
        result = screener.run(["AAA", "BBB", "CCC", "DDD", "EEE"], top_n=2)

        assert sorted(c.factor_rank for c in result.scored) == [1, 2]

    def test_ticker_without_data_is_excluded_not_fatal(self, screener, fake_market):
        fake_market.price_overrides["DEAD"] = pd.DataFrame()

        result = screener.run(["AAA", "BBB", "DEAD"], top_n=5)

        assert "DEAD" in result.excluded
        assert result.excluded["DEAD"].startswith("data unavailable")
        assert len(result.scored) == 2

    def test_filters_exclude_before_ranking(self, screener, fake_market):
        fake_market.info_overrides["OIL"] = {"sector": "Energy", "industry": "Oil & Gas"}

        result = screener.run(
            ["AAA", "BBB", "OIL"], filters=ScreenFilters(exclude_sectors=("Energy",))
        )

        assert result.excluded["OIL"].startswith("filtered")
        assert "OIL" not in {c.ticker for c in result.ranked}

    def test_stage_two_reuses_stage_one_prices(self, screener, fake_market):
        screener.run(["AAA", "BBB", "CCC"], top_n=3)

        assert fake_market.calls[("history", "AAA")] == 1
        assert fake_market.calls[("info", "AAA")] == 1

    def test_skips_news_and_holders(self, screener, fake_market):
        screener.run(["AAA", "BBB"], top_n=2)

        assert fake_market.calls[("news", "AAA")] == 0
        assert fake_market.calls[("institutional_holders", "AAA")] == 0

    def test_single_survivor_is_still_scored(self, screener):
        result = screener.run(["AAA"], top_n=5)

        assert result.scored[0].scoring is not None
        assert result.scored[0].factor_rank is None

    def test_save_writes_csv_json_and_latest(self, screener, tmp_path):
        result = screener.run(["AAA", "BBB"], top_n=2, universe_label="test")

        paths = save_screen(result, str(tmp_path), output_format="json")

        assert {p.suffix for p in paths} == {".csv", ".json"}
        latest = json.loads((tmp_path / "_screens" / "latest.json").read_text(encoding="utf-8"))
        assert latest["meta"]["universe"] == "test"
        assert len(latest["results"]) == 2


def test_screen_command_end_to_end(fake_market, tmp_path):
    result = CliRunner().invoke(
        cli,
        ["--output-dir", str(tmp_path), "screen", "AAA", "BBB", "CCC", "--top", "2"],
    )

    assert result.exit_code == 0, result.output
    assert "SCREEN: tickers" in result.output
    assert "Next: quant report" in result.output
    assert (tmp_path / "_screens" / "latest.csv").exists()


def test_screen_command_requires_universe():
    result = CliRunner().invoke(cli, ["screen"])

    assert result.exit_code != 0
    assert "sp500" in result.output
