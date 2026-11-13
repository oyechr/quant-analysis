"""
13F source and CUSIP enrichment (review Batch G).

A fake EDGAR serves the submission list, filing indexes, primary documents
and information tables, so the real Edgar13FSource runs offline.
"""

import json
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

from src.discovery.enrichment import HoldingEnricher, is_cusip, yahoo_symbol
from src.discovery.models import Holding, TrackedPortfolio
from src.discovery.sources.edgar_13f import (
    Edgar13FSource,
    Filing,
    aggregate_holdings,
    diff_holdings,
    latest_periods,
    parse_information_table,
)

CIK = "0000000042"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/42"

# ============================================================
# Fake EDGAR
# ============================================================


def info_table(*rows: tuple, namespace: bool = True) -> bytes:
    """rows: (name, cusip, value, shares[, putCall[, sshPrnamtType]])"""
    ns = ' xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"'
    entries = []
    for row in rows:
        name, cusip, value, shares = row[:4]
        put_call = f"<putCall>{row[4]}</putCall>" if len(row) > 4 and row[4] else ""
        kind = row[5] if len(row) > 5 else "SH"
        entries.append(
            f"<infoTable><nameOfIssuer>{name}</nameOfIssuer><cusip>{cusip}</cusip>"
            f"<value>{value}</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>"
            f"<sshPrnamtType>{kind}</sshPrnamtType></shrsOrPrnAmt>{put_call}</infoTable>"
        )
    return (
        f"<informationTable{ns if namespace else ''}>{''.join(entries)}</informationTable>".encode()
    )


def primary_doc(amendment_type: str) -> bytes:
    return (
        '<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData>'
        "<coverPage><isAmendment>true</isAmendment><amendmentInfo>"
        f"<amendmentType>{amendment_type}</amendmentType></amendmentInfo></coverPage>"
        "</formData></edgarSubmission>"
    ).encode()


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def json(self):
        return json.loads(self.content)


class FakeEdgar:
    """filings: (form, accession, filing date, report date, table bytes, amendment type)"""

    def __init__(self, filings: list[tuple]):
        self.filings = filings
        self.requests: list[str] = []
        self.offline = False

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.requests.append(url)
        if self.offline:
            raise requests.ConnectionError("offline")
        if url.endswith(f"CIK{CIK}.json"):
            recent = {
                "form": [f[0] for f in self.filings],
                "accessionNumber": [f[1] for f in self.filings],
                "filingDate": [f[2] for f in self.filings],
                "reportDate": [f[3] for f in self.filings],
            }
            return FakeResponse(json.dumps({"filings": {"recent": recent}}).encode())
        for _form, accession, _, _, table, kind in self.filings:
            base = f"{ARCHIVE}/{accession.replace('-', '')}"
            if url == f"{base}/index.json":
                items = [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]
                return FakeResponse(json.dumps({"directory": {"item": items}}).encode())
            if url == f"{base}/infotable.xml":
                return FakeResponse(table)
            if url == f"{base}/primary_doc.xml":
                return FakeResponse(primary_doc(kind or ""))
        raise requests.HTTPError(f"404 {url}")


def make_source(edgar: FakeEdgar) -> Edgar13FSource:
    source = Edgar13FSource(
        filers=[{"name": "Test Fund", "cik": CIK}], cache_dir="data", user_agent="Test test@test"
    )
    source._get = edgar.get  # type: ignore[method-assign]
    return source


Q1 = info_table(("APPLE INC", "037833100", 1000, 10), ("META", "30303M102", 500, 5))
Q2 = info_table(("APPLE INC", "037833100", 1200, 12), ("META", "30303M102", 500, 5))
Q2_NEW_HOLDINGS = info_table(("NVIDIA", "67066G104", 300, 3))


def actions(portfolio: TrackedPortfolio) -> dict[str, str]:
    return {h.ticker: str(h.action) for h in portfolio.holdings}


# ============================================================
# Parsing
# ============================================================


class TestParse:
    def test_duplicate_cusip_rows_count_once(self):
        # Reproduces the review's case: two rows of one CUSIP (two managers).
        # The old diff summed them into the first row and kept the second, so
        # $100k counted as $150k.
        rows = parse_information_table(
            info_table(
                ("BERKSHIRE", "084670702", 50_000, 100), ("BERKSHIRE", "084670702", 50_000, 100)
            )
        )
        result = diff_holdings(rows, [])
        assert len(result) == 1
        assert result[0].value == 100_000
        assert result[0].shares == 200
        assert sum(h.value or 0 for h in result) == 100_000

    def test_options_and_principal_amounts_are_not_stock(self):
        rows = parse_information_table(
            info_table(
                ("SPDR S&amp;P 500", "78462F103", 9_000, 20, "Put"),
                ("TESLA", "88160R101", 4_000, 10, "Call"),
                ("CONVERTIBLE NOTE", "12345AAB1", 1_000, 1_000_000, None, "PRN"),
                ("APPLE INC", "037833100", 1_000, 10),
            )
        )
        assert [h.ticker for h in rows] == ["037833100"]

    def test_reads_tables_without_a_namespace(self):
        rows = parse_information_table(
            info_table(("APPLE INC", "037833100", 1000, 10), namespace=False)
        )
        assert rows[0].ticker == "037833100"
        assert rows[0].value == 1000
        assert rows[0].shares == 10

    def test_aggregate_and_diff_dont_modify_their_input(self):
        current = [Holding("X", "X", shares=10, value=100), Holding("X", "X", shares=5, value=50)]
        previous = [Holding("X", "X", shares=10, value=90), Holding("X", "X", shares=5, value=45)]

        aggregate_holdings(current)
        diff_holdings(current, previous)

        assert [(h.shares, h.value, h.action) for h in current] == [(10, 100, None), (5, 50, None)]
        assert [(h.shares, h.value) for h in previous] == [(10, 90), (5, 45)]


class TestLatestPeriods:
    def test_two_latest_report_dates_newest_first(self):
        def f(form, acc, filed, period):
            return Filing(form, acc, datetime.fromisoformat(filed), datetime.fromisoformat(period))

        filings = [
            f("13F-HR/A", "a4", "2026-09-01", "2026-03-31"),  # a late amendment of Q1
            f("13F-HR", "a3", "2026-08-14", "2026-06-30"),
            f("13F-HR", "a2", "2026-05-15", "2026-03-31"),
            f("13F-HR", "a1", "2026-02-14", "2025-12-31"),
        ]
        periods = latest_periods(filings)
        assert [[x.accession for x in p] for p in periods] == [["a3"], ["a4", "a2"]]


# ============================================================
# Fetching: amendments, actions, weights
# ============================================================


class TestFetch:
    def test_new_holdings_amendment_adds_to_the_original(self):
        # The old code took the amendment (only NVIDIA) as the whole quarter,
        # so Apple and Meta read as exits
        edgar = FakeEdgar(
            [
                (
                    "13F-HR/A",
                    "0000000042-26-000003",
                    "2026-08-20",
                    "2026-06-30",
                    Q2_NEW_HOLDINGS,
                    "NEW HOLDINGS",
                ),
                ("13F-HR", "0000000042-26-000002", "2026-08-14", "2026-06-30", Q2, None),
                ("13F-HR", "0000000042-26-000001", "2026-05-15", "2026-03-31", Q1, None),
            ]
        )
        portfolio = make_source(edgar).fetch_portfolios()[0]

        assert actions(portfolio) == {"037833100": "add", "30303M102": "hold", "67066G104": "new"}
        assert portfolio.period_of_report == datetime(2026, 6, 30)
        assert portfolio.filing_date == datetime(2026, 8, 14)

    def test_restatement_replaces_the_original(self):
        restated = info_table(("APPLE INC", "037833100", 1000, 10))
        edgar = FakeEdgar(
            [
                (
                    "13F-HR/A",
                    "0000000042-26-000003",
                    "2026-08-20",
                    "2026-06-30",
                    restated,
                    "RESTATEMENT",
                ),
                ("13F-HR", "0000000042-26-000002", "2026-08-14", "2026-06-30", Q2, None),
                ("13F-HR", "0000000042-26-000001", "2026-05-15", "2026-03-31", Q1, None),
            ]
        )
        portfolio = make_source(edgar).fetch_portfolios()[0]

        assert actions(portfolio) == {"037833100": "hold", "30303M102": "exit"}
        # The original's information table is never read
        assert f"{ARCHIVE}/000000004226000002/infotable.xml" not in edgar.requests

    def test_previous_quarter_is_by_report_date_not_filing_order(self):
        # A late amendment of an older quarter isn't the "previous filing"
        old = info_table(("META", "30303M102", 1, 1))
        edgar = FakeEdgar(
            [
                (
                    "13F-HR/A",
                    "0000000042-26-000009",
                    "2026-09-01",
                    "2025-12-31",
                    old,
                    "RESTATEMENT",
                ),
                ("13F-HR", "0000000042-26-000002", "2026-08-14", "2026-06-30", Q2, None),
                ("13F-HR", "0000000042-26-000001", "2026-05-15", "2026-03-31", Q1, None),
            ]
        )
        portfolio = make_source(edgar).fetch_portfolios()[0]
        assert actions(portfolio) == {"037833100": "add", "30303M102": "hold"}

    def test_weights_are_shares_of_the_held_value(self):
        edgar = FakeEdgar(
            [("13F-HR", "0000000042-26-000002", "2026-08-14", "2026-06-30", Q2, None)]
        )
        portfolio = make_source(edgar).fetch_portfolios()[0]
        weights = {h.ticker: h.weight for h in portfolio.holdings}
        assert weights["037833100"] == pytest.approx(1200 / 1700 * 100)
        assert weights["30303M102"] == pytest.approx(500 / 1700 * 100)

    def test_default_user_agent_warns(self, caplog):
        source = Edgar13FSource(filers=[], cache_dir="data")
        # Offline, so the default filers fail fast instead of reaching the socket guard
        edgar = FakeEdgar([])
        edgar.offline = True
        source._get = edgar.get  # type: ignore[method-assign]
        with caplog.at_level(logging.WARNING):
            source.fetch_portfolios()
        assert "edgar_user_agent" in caplog.text

    def test_sec_requests_are_retried_on_throttling(self):
        source = Edgar13FSource(filers=[], cache_dir="data", user_agent="Test test@test")
        retry = source._session.get_adapter("https://data.sec.gov/x").max_retries
        assert retry.total == 3
        assert 429 in retry.status_forcelist and 503 in retry.status_forcelist


# ============================================================
# Cache
# ============================================================


def _two_quarters() -> FakeEdgar:
    return FakeEdgar(
        [
            ("13F-HR", "0000000042-26-000002", "2026-08-14", "2026-06-30", Q2, None),
            ("13F-HR", "0000000042-26-000001", "2026-05-15", "2026-03-31", Q1, None),
        ]
    )


def _age_cache(days: float) -> None:
    from pathlib import Path

    path = Path("data/_discovery/edgar_13f") / f"{CIK}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fetched_at"] = (datetime.now() - timedelta(days=days)).isoformat()
    path.write_text(json.dumps(data), encoding="utf-8")


class TestCache:
    def test_recent_cache_needs_no_request(self):
        make_source(_two_quarters()).fetch_portfolios()
        edgar = _two_quarters()
        edgar.offline = True

        portfolio = make_source(edgar).fetch_portfolios()[0]

        assert edgar.requests == []
        assert actions(portfolio)["037833100"] == "add"

    def test_old_cache_is_kept_when_no_filing_changed(self):
        make_source(_two_quarters()).fetch_portfolios()
        _age_cache(days=3)
        edgar = _two_quarters()

        make_source(edgar).fetch_portfolios()

        assert len(edgar.requests) == 1  # the submission list only
        edgar.requests.clear()
        make_source(edgar).fetch_portfolios()  # and the check renewed the cache
        assert edgar.requests == []

    def test_a_new_quarter_is_fetched(self):
        # The old cache never expired: a new quarter was never seen
        make_source(_two_quarters()).fetch_portfolios()
        _age_cache(days=3)
        q3 = info_table(("APPLE INC", "037833100", 1200, 12))
        edgar = FakeEdgar(
            [
                ("13F-HR", "0000000042-26-000005", "2026-11-14", "2026-09-30", q3, None),
                *_two_quarters().filings,
            ]
        )

        portfolio = make_source(edgar).fetch_portfolios()[0]

        assert portfolio.period_of_report == datetime(2026, 9, 30)
        assert actions(portfolio) == {"037833100": "hold", "30303M102": "exit"}

    def test_old_cache_is_used_when_edgar_is_unreachable(self, caplog):
        make_source(_two_quarters()).fetch_portfolios()
        _age_cache(days=3)
        edgar = _two_quarters()
        edgar.offline = True

        with caplog.at_level(logging.WARNING):
            portfolios = make_source(edgar).fetch_portfolios()

        assert actions(portfolios[0])["037833100"] == "add"
        assert "using the cached filing" in caplog.text

    def test_no_cache_refetches(self):
        make_source(_two_quarters()).fetch_portfolios()
        edgar = _two_quarters()
        make_source(edgar).fetch_portfolios(use_cache=False)
        assert any(url.endswith("infotable.xml") for url in edgar.requests)


# ============================================================
# Enrichment: CUSIP -> ticker (OpenFIGI) and sectors (DataFetcher)
# ============================================================


def figi_response(answers: list) -> MagicMock:
    response = MagicMock()
    response.json.return_value = answers
    return response


def make_enricher(*answers: list, info: dict | None = None, api_key: str = "") -> HoldingEnricher:
    fetcher = MagicMock()
    fetcher.get_ticker_info.side_effect = lambda t: (info or {}).get(t, {})
    enricher = HoldingEnricher(
        cache_dir="data", fetcher=fetcher, api_key=api_key, sleep=MagicMock()
    )
    enricher._session = MagicMock()
    enricher._session.post.side_effect = [figi_response(a) for a in answers]
    return enricher


class TestEnrichment:
    def test_cusips_resolve_through_openfigi_with_share_classes_kept(self):
        enricher = make_enricher(
            [
                {"data": [{"ticker": "GOOGL", "marketSector": "Equity"}]},
                {"data": [{"ticker": "GOOG", "marketSector": "Equity"}]},
                {"data": [{"ticker": "BRK/B", "marketSector": "Equity"}]},
            ]
        )
        result = enricher.resolve_cusips(["02079K305", "02079K107", "084670702"])
        assert result == {"02079K305": "GOOGL", "02079K107": "GOOG", "084670702": "BRK-B"}
        job = enricher._session.post.call_args.kwargs["json"][0]
        assert job == {"idType": "ID_CUSIP", "idValue": "02079K305", "exchCode": "US"}

    def test_network_error_caches_nothing(self):
        # The old code cached a CUSIP as unresolvable after any failure, forever
        enricher = make_enricher()
        enricher._session.post.side_effect = requests.ConnectionError("down")
        assert enricher.resolve_cusips(["037833100"]) == {}
        enricher._save_caches()

        retry = make_enricher([{"data": [{"ticker": "AAPL", "marketSector": "Equity"}]}])
        assert retry.resolve_cusips(["037833100"]) == {"037833100": "AAPL"}

    def test_unknown_cusip_is_retried_after_the_miss_ttl(self):
        unknown = [{"warning": "No identifier found."}]
        enricher = make_enricher(unknown, unknown)  # both forms
        assert enricher.resolve_cusips(["99999X999"]) == {}
        enricher._save_caches()

        again = make_enricher()
        assert again.resolve_cusips(["99999X999"]) == {}
        again._session.post.assert_not_called()

        again._misses["99999X999"] = (datetime.now() - timedelta(days=31)).date().isoformat()
        again._session.post.side_effect = [figi_response(unknown), figi_response(unknown)]
        again.resolve_cusips(["99999X999"])
        assert again._session.post.call_count == 2

    def test_a_cins_miss_is_asked_again_as_a_cins(self):
        # Seen live: ASML (N07059210), Wix, Tower, Camtek and Chubb stayed CUSIPs
        enricher = make_enricher(
            [{"warning": "No identifier found."}, {"warning": "No identifier found."}],
            [
                {
                    "data": [
                        {"ticker": "ASML", "exchCode": "NA", "marketSector": "Equity"},
                        {"ticker": "ASML", "exchCode": "US", "marketSector": "Equity"},
                    ]
                },
                {"data": [{"ticker": "ROKU", "exchCode": "UW", "marketSector": "Equity"}]},
            ],
        )

        result = enricher.resolve_cusips(["N07059210", "77543R102"])

        assert result == {"N07059210": "ASML", "77543R102": "ROKU"}
        retry = enricher._session.post.call_args_list[1].kwargs["json"]
        assert retry == [
            {"idType": "ID_CINS", "idValue": "N07059210"},
            {"idType": "ID_CUSIP", "idValue": "77543R102"},
        ]

    def test_a_listing_outside_the_us_is_no_answer(self):
        enricher = make_enricher(
            [{"warning": "No identifier found."}],
            [{"data": [{"ticker": "TSEM", "exchCode": "IT", "marketSector": "Equity"}]}],
        )
        assert enricher.resolve_cusips(["M87915274"]) == {}
        assert "M87915274" in enricher._misses

    def test_the_old_name_search_map_is_not_trusted(self):
        # Seen live: the old cusip_map.json had both Alphabet classes as GOOG
        from pathlib import Path

        old = Path("data/_discovery/enrichment/cusip_map.json")
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text(json.dumps({"02079K305": "GOOG"}), encoding="utf-8")
        enricher = make_enricher([{"data": [{"ticker": "GOOGL", "marketSector": "Equity"}]}])

        assert enricher.resolve_cusips(["02079K305"]) == {"02079K305": "GOOGL"}
        enricher._save_caches()
        saved = json.loads(Path("data/_discovery/enrichment/cusip_tickers.json").read_text())
        assert saved == {"02079K305": "GOOGL"}

    def test_cached_hits_need_no_request(self):
        enricher = make_enricher([{"data": [{"ticker": "MSFT", "marketSector": "Equity"}]}])
        enricher.resolve_cusips(["594918104"])
        enricher._save_caches()

        again = make_enricher()
        assert again.resolve_cusips(["594918104"]) == {"594918104": "MSFT"}
        again._session.post.assert_not_called()

    def test_batches_and_pacing_without_a_key(self):
        cusips = [f"00000{i:03d}X" for i in range(25)]
        enricher = make_enricher(
            *[
                [{"data": [{"ticker": f"T{i}", "marketSector": "Equity"}]} for i in range(n)]
                for n in (10, 10, 5)
            ]
        )
        result = enricher.resolve_cusips(cusips)
        assert len(result) == 25
        assert enricher._session.post.call_count == 3
        assert enricher._sleep.call_count == 2  # nothing before the first request

    def test_sectors_come_from_the_fetcher_and_misses_arent_cached(self):
        enricher = make_enricher(
            [
                {"data": [{"ticker": "AAPL", "marketSector": "Equity"}]},
                {"data": [{"ticker": "SPY", "marketSector": "Equity"}]},
            ],
            info={
                "AAPL": {"sector": "Technology", "industry": "Consumer Electronics"},
                "SPY": {"sector": "N/A", "industry": "N/A"},
            },
        )
        portfolio = TrackedPortfolio(
            name="F",
            source="test",
            holdings=[Holding("037833100", "APPLE INC"), Holding("78462F103", "SPDR S&P 500")],
        )

        enricher.enrich_portfolio(portfolio)

        aapl, spy = portfolio.holdings
        assert (aapl.ticker, aapl.sector, aapl.industry) == (
            "AAPL",
            "Technology",
            "Consumer Electronics",
        )
        assert (spy.ticker, spy.sector) == ("SPY", None)
        assert set(enricher._sector_map) == {"AAPL"}

    def test_helpers(self):
        assert is_cusip("037833100") and not is_cusip("AAPL") and not is_cusip("ABCDEFGHI")
        assert yahoo_symbol("BRK/B") == "BRK-B"
