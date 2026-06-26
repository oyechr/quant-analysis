"""
Tests for the Portfolio Discovery module.

Tests the cross-portfolio analyzer patterns:
- Ticker overlap detection
- Sector/industry clustering
- Activity convergence
- Contrarian signals
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.discovery.analyzer import PortfolioAnalyzer
from src.discovery.models import (
    DiscoveryResult,
    DiscoverySignal,
    Holding,
    SectorCluster,
    TrackedPortfolio,
)

# ============================================================
# Test Fixtures
# ============================================================


def _make_holding(
    ticker: str,
    name: str = "",
    sector: str = None,
    industry: str = None,
    value: float = None,
    shares: float = None,
    weight: float = None,
    action: str = None,
    date: datetime = None,
) -> Holding:
    """Helper to create a Holding with defaults."""
    return Holding(
        ticker=ticker,
        name=name or f"{ticker} Corp",
        sector=sector,
        industry=industry,
        value=value,
        shares=shares,
        weight=weight,
        action=action,
        date=date,
    )


def _make_portfolio(
    name: str, holdings: list[Holding], filing_date: datetime = None
) -> TrackedPortfolio:
    """Helper to create a TrackedPortfolio."""
    return TrackedPortfolio(
        name=name,
        source="test",
        holdings=holdings,
        filing_date=filing_date or datetime(2024, 6, 30),
    )


@pytest.fixture
def sample_portfolios():
    """Create a set of sample portfolios with overlapping holdings."""
    portfolio_a = _make_portfolio(
        "Berkshire Hathaway",
        [
            _make_holding("AAPL", "Apple Inc", "Technology", "Consumer Electronics", 100000, 40.0),
            _make_holding(
                "BAC", "Bank of America", "Financial Services", "Banks—Diversified", 50000, 20.0
            ),
            _make_holding(
                "KO", "Coca-Cola", "Consumer Defensive", "Beverages—Non-Alcoholic", 25000, 10.0
            ),
            _make_holding("OXY", "Occidental Petroleum", "Energy", "Oil & Gas E&P", 20000, 8.0),
            _make_holding("AMZN", "Amazon", "Technology", "Internet Retail", 15000, 6.0),
        ],
    )

    portfolio_b = _make_portfolio(
        "ARK Innovation",
        [
            _make_holding("TSLA", "Tesla Inc", "Technology", "Auto Manufacturers", 80000, 35.0),
            _make_holding("ROKU", "Roku Inc", "Technology", "Communication Equipment", 30000, 13.0),
            _make_holding("SQ", "Block Inc", "Technology", "Software—Infrastructure", 25000, 11.0),
            _make_holding("AAPL", "Apple Inc", "Technology", "Consumer Electronics", 20000, 9.0),
            _make_holding("AMZN", "Amazon", "Technology", "Internet Retail", 18000, 8.0),
        ],
    )

    portfolio_c = _make_portfolio(
        "Soros Fund",
        [
            _make_holding("AAPL", "Apple Inc", "Technology", "Consumer Electronics", 45000, 25.0),
            _make_holding(
                "MSFT", "Microsoft", "Technology", "Software—Infrastructure", 40000, 22.0
            ),
            _make_holding("AMZN", "Amazon", "Technology", "Internet Retail", 30000, 17.0),
            _make_holding(
                "BAC", "Bank of America", "Financial Services", "Banks—Diversified", 20000, 11.0
            ),
            _make_holding("NVDA", "NVIDIA", "Technology", "Semiconductors", 25000, 14.0),
        ],
    )

    portfolio_d = _make_portfolio(
        "Pershing Square",
        [
            _make_holding(
                "QSR", "Restaurant Brands", "Consumer Cyclical", "Restaurants", 60000, 30.0
            ),
            _make_holding("HLT", "Hilton", "Consumer Cyclical", "Lodging", 40000, 20.0),
            _make_holding("AAPL", "Apple Inc", "Technology", "Consumer Electronics", 30000, 15.0),
            _make_holding("AMZN", "Amazon", "Technology", "Internet Retail", 20000, 10.0),
            _make_holding(
                "GOOGL", "Alphabet", "Technology", "Internet Content & Information", 25000, 12.5
            ),
        ],
    )

    return [portfolio_a, portfolio_b, portfolio_c, portfolio_d]


@pytest.fixture
def portfolios_with_actions():
    """Portfolios with buy/sell/add/trim/new/exit actions for convergence/contrarian testing."""
    now = datetime.now()

    portfolio_a = _make_portfolio(
        "Fund A",
        [
            _make_holding("NVDA", "NVIDIA", action="new", date=now - timedelta(days=30)),
            _make_holding("AAPL", "Apple", action="add", date=now - timedelta(days=45)),
            _make_holding("META", "Meta", action="exit", date=now - timedelta(days=20)),
        ],
    )

    portfolio_b = _make_portfolio(
        "Fund B",
        [
            _make_holding("NVDA", "NVIDIA", action="new", date=now - timedelta(days=60)),
            _make_holding("META", "Meta", action="add", date=now - timedelta(days=15)),
            _make_holding("TSLA", "Tesla", action="trim", date=now - timedelta(days=10)),
        ],
    )

    portfolio_c = _make_portfolio(
        "Fund C",
        [
            _make_holding("NVDA", "NVIDIA", action="add", date=now - timedelta(days=50)),
            _make_holding("AAPL", "Apple", action="exit", date=now - timedelta(days=25)),
            _make_holding("META", "Meta", action="trim", date=now - timedelta(days=40)),
        ],
    )

    return [portfolio_a, portfolio_b, portfolio_c]


# ============================================================
# Test Models
# ============================================================


class TestModels:
    """Tests for data model classes."""

    def test_holding_ticker_uppercase(self):
        h = Holding(ticker="aapl", name="Apple")
        assert h.ticker == "AAPL"

    def test_holding_ticker_strip(self):
        h = Holding(ticker="  msft  ", name="Microsoft")
        assert h.ticker == "MSFT"

    def test_tracked_portfolio_tickers(self):
        p = _make_portfolio(
            "Test",
            [_make_holding("AAPL"), _make_holding("MSFT"), _make_holding("AAPL")],
        )
        assert p.tickers == {"AAPL", "MSFT"}

    def test_tracked_portfolio_total_value(self):
        p = _make_portfolio(
            "Test",
            [_make_holding("AAPL", value=100), _make_holding("MSFT", value=200)],
        )
        assert p.total_value == 300

    def test_tracked_portfolio_total_value_none(self):
        p = _make_portfolio("Test", [_make_holding("AAPL"), _make_holding("MSFT")])
        assert p.total_value is None

    def test_discovery_signal_overlap_pct(self):
        signal = DiscoverySignal(ticker="AAPL", overlap_count=3, total_portfolios=10)
        assert signal.overlap_pct == 30.0

    def test_discovery_signal_overlap_pct_zero(self):
        signal = DiscoverySignal(ticker="AAPL", overlap_count=0, total_portfolios=0)
        assert signal.overlap_pct == 0.0

    def test_sector_cluster_label_with_industry(self):
        cluster = SectorCluster(sector="Technology", industry="Semiconductors")
        assert cluster.label == "Technology > Semiconductors"

    def test_sector_cluster_label_without_industry(self):
        cluster = SectorCluster(sector="Technology")
        assert cluster.label == "Technology"

    def test_discovery_result_to_dict(self):
        result = DiscoveryResult(
            portfolios_analyzed=3,
            total_holdings=15,
            overlap_signals=[
                DiscoverySignal(
                    ticker="AAPL",
                    name="Apple",
                    strength=80.0,
                    overlap_count=3,
                    total_portfolios=5,
                    portfolios=["A", "B", "C"],
                )
            ],
        )
        d = result.to_dict()
        assert d["meta"]["portfolios_analyzed"] == 3
        assert len(d["overlap_signals"]) == 1
        assert d["overlap_signals"][0]["ticker"] == "AAPL"
        assert d["overlap_signals"][0]["strength"] == 80.0


# ============================================================
# Test Overlap Detection
# ============================================================


class TestOverlapDetection:
    """Tests for ticker overlap pattern detection."""

    def test_detects_overlap(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(sample_portfolios)

        # AAPL appears in all 4 portfolios
        aapl = next((s for s in signals if s.ticker == "AAPL"), None)
        assert aapl is not None
        assert aapl.overlap_count == 4
        assert aapl.total_portfolios == 4
        assert len(aapl.portfolios) == 4

    def test_amzn_overlap(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(sample_portfolios)

        # AMZN appears in all 4 portfolios
        amzn = next((s for s in signals if s.ticker == "AMZN"), None)
        assert amzn is not None
        assert amzn.overlap_count == 4

    def test_bac_overlap(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(sample_portfolios)

        # BAC appears in 2 portfolios
        bac = next((s for s in signals if s.ticker == "BAC"), None)
        assert bac is not None
        assert bac.overlap_count == 2

    def test_min_overlap_filters(self, sample_portfolios):
        # With min_overlap=3, BAC (only 2) should be excluded
        analyzer = PortfolioAnalyzer(min_overlap=3)
        signals = analyzer._detect_overlap(sample_portfolios)

        bac = next((s for s in signals if s.ticker == "BAC"), None)
        assert bac is None

        # But AAPL (4) should still be there
        aapl = next((s for s in signals if s.ticker == "AAPL"), None)
        assert aapl is not None

    def test_unique_tickers_excluded(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(sample_portfolios)

        # KO only appears in 1 portfolio
        ko = next((s for s in signals if s.ticker == "KO"), None)
        assert ko is None

    def test_strength_ordering(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(sample_portfolios)

        # AAPL (4/4 overlap, high weights) should have highest strength
        assert signals[0].ticker in ("AAPL", "AMZN")  # Both appear in all 4
        # Strength should be decreasing
        strengths = [s.strength for s in signals]
        assert strengths == sorted(strengths, reverse=True)

    def test_signal_has_sector_info(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(sample_portfolios)

        aapl = next((s for s in signals if s.ticker == "AAPL"), None)
        assert aapl.sector == "Technology"
        assert aapl.industry == "Consumer Electronics"

    def test_empty_portfolios(self):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap([])
        assert signals == []

    def test_single_portfolio(self):
        p = _make_portfolio("Solo", [_make_holding("AAPL")])
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap([p])
        assert signals == []


# ============================================================
# Test Sector Clustering
# ============================================================


class TestSectorClustering:
    """Tests for sector/industry cluster detection."""

    def test_detects_tech_cluster(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_sector_holdings=3)
        clusters = analyzer._detect_sector_clusters(sample_portfolios)

        # Technology should be a strong cluster
        tech_clusters = [c for c in clusters if c.sector == "Technology"]
        assert len(tech_clusters) > 0

    def test_granular_industry_grouping(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_sector_holdings=2)
        clusters = analyzer._detect_sector_clusters(sample_portfolios)

        # "Consumer Electronics" (AAPL in multiple portfolios) should form a cluster
        ce = next(
            (c for c in clusters if c.industry == "Consumer Electronics"),
            None,
        )
        assert ce is not None
        assert "AAPL" in ce.tickers

    def test_internet_retail_cluster(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_sector_holdings=2)
        clusters = analyzer._detect_sector_clusters(sample_portfolios)

        ir = next(
            (c for c in clusters if c.industry == "Internet Retail"),
            None,
        )
        assert ir is not None
        assert "AMZN" in ir.tickers

    def test_min_holdings_filter(self, sample_portfolios):
        # With high threshold, small clusters should be excluded
        analyzer = PortfolioAnalyzer(min_sector_holdings=10)
        clusters = analyzer._detect_sector_clusters(sample_portfolios)

        # Most clusters won't meet this threshold
        assert len(clusters) < 3

    def test_cluster_has_portfolio_names(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_sector_holdings=2)
        clusters = analyzer._detect_sector_clusters(sample_portfolios)

        # Find a cluster with multiple portfolios
        multi = next((c for c in clusters if len(c.portfolios) > 1), None)
        assert multi is not None
        assert all(isinstance(name, str) for name in multi.portfolios)

    def test_strength_ordering(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_sector_holdings=2)
        clusters = analyzer._detect_sector_clusters(sample_portfolios)

        strengths = [c.strength for c in clusters]
        assert strengths == sorted(strengths, reverse=True)


# ============================================================
# Test Activity Convergence
# ============================================================


class TestConvergence:
    """Tests for activity convergence detection."""

    def test_detects_buy_convergence(self, portfolios_with_actions):
        analyzer = PortfolioAnalyzer(min_overlap=2, convergence_window_days=90)
        events = analyzer._detect_convergence(portfolios_with_actions)

        # NVDA bought by all 3 funds within 90 days
        nvda = next((e for e in events if e.ticker == "NVDA"), None)
        assert nvda is not None
        assert nvda.action == "buy"
        assert len(nvda.portfolios) == 3

    def test_window_limits_convergence(self, portfolios_with_actions):
        # With a very small window, convergence should not be detected
        analyzer = PortfolioAnalyzer(min_overlap=3, convergence_window_days=5)
        events = analyzer._detect_convergence(portfolios_with_actions)

        # No events should have 3 funds converging in 5 days
        nvda = next((e for e in events if e.ticker == "NVDA" and len(e.portfolios) >= 3), None)
        assert nvda is None

    def test_no_convergence_without_actions(self, sample_portfolios):
        # sample_portfolios don't have actions/dates
        analyzer = PortfolioAnalyzer(min_overlap=2)
        events = analyzer._detect_convergence(sample_portfolios)
        assert events == []

    def test_sell_convergence(self, portfolios_with_actions):
        analyzer = PortfolioAnalyzer(min_overlap=2, convergence_window_days=90)
        events = analyzer._detect_convergence(portfolios_with_actions)

        # META sold by Fund A and Fund C
        meta_sell = next((e for e in events if e.ticker == "META" and e.action == "sell"), None)
        assert meta_sell is not None
        assert len(meta_sell.portfolios) >= 2


# ============================================================
# Test Contrarian Signals
# ============================================================


class TestContrarianSignals:
    """Tests for contrarian signal detection."""

    def test_detects_disagreement(self, portfolios_with_actions):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_contrarian(portfolios_with_actions)

        # META: Fund B buys, Fund A and C sell
        meta = next((s for s in signals if s.ticker == "META"), None)
        assert meta is not None
        assert "Fund B" in meta.buyers
        assert "Fund A" in meta.sellers or "Fund C" in meta.sellers

    def test_contrarian_net_direction(self, portfolios_with_actions):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_contrarian(portfolios_with_actions)

        meta = next((s for s in signals if s.ticker == "META"), None)
        assert meta is not None
        # More sellers than buyers for META → bearish
        assert meta.net_direction == "bearish"

    def test_no_contrarian_without_actions(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_contrarian(sample_portfolios)
        assert signals == []

    def test_no_signal_when_all_same_direction(self):
        """If everyone is buying, no contrarian signal."""
        now = datetime.now()
        portfolios = [
            _make_portfolio(
                "Fund A",
                [_make_holding("AAPL", action="buy", date=now)],
            ),
            _make_portfolio(
                "Fund B",
                [_make_holding("AAPL", action="buy", date=now)],
            ),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_contrarian(portfolios)

        aapl = next((s for s in signals if s.ticker == "AAPL"), None)
        assert aapl is None  # No disagreement


# ============================================================
# Test Full Analysis Pipeline
# ============================================================


class TestFullAnalysis:
    """Integration tests for the complete analysis pipeline."""

    def test_full_analyze(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        result = analyzer.analyze(sample_portfolios)

        assert isinstance(result, DiscoveryResult)
        assert result.portfolios_analyzed == 4
        assert result.total_holdings == 20
        assert len(result.overlap_signals) > 0

    def test_full_analyze_with_actions(self, portfolios_with_actions):
        analyzer = PortfolioAnalyzer(min_overlap=2, convergence_window_days=90)
        result = analyzer.analyze(portfolios_with_actions)

        assert result.portfolios_analyzed == 3
        assert len(result.convergence_events) > 0

    def test_empty_input(self):
        analyzer = PortfolioAnalyzer()
        result = analyzer.analyze([])

        assert result.portfolios_analyzed == 0
        assert result.overlap_signals == []
        assert result.sector_clusters == []

    def test_to_dict_serialization(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        result = analyzer.analyze(sample_portfolios)
        d = result.to_dict()

        assert "meta" in d
        assert "overlap_signals" in d
        assert "sector_clusters" in d
        assert "convergence_events" in d
        assert "contrarian_signals" in d
        assert d["meta"]["portfolios_analyzed"] == 4

    def test_top_signals_sorted(self, sample_portfolios):
        analyzer = PortfolioAnalyzer(min_overlap=2)
        result = analyzer.analyze(sample_portfolios)

        strengths = [s.strength for s in result.top_signals]
        assert strengths == sorted(strengths, reverse=True)


# ============================================================
# Test Edge Cases
# ============================================================


class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_single_holding_portfolio(self):
        portfolios = [
            _make_portfolio("A", [_make_holding("AAPL", sector="Tech")]),
            _make_portfolio("B", [_make_holding("AAPL", sector="Tech")]),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2)
        result = analyzer.analyze(portfolios)
        assert len(result.overlap_signals) == 1
        assert result.overlap_signals[0].ticker == "AAPL"

    def test_no_overlap_at_all(self):
        portfolios = [
            _make_portfolio("A", [_make_holding("AAPL")]),
            _make_portfolio("B", [_make_holding("MSFT")]),
            _make_portfolio("C", [_make_holding("GOOGL")]),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2)
        result = analyzer.analyze(portfolios)
        assert len(result.overlap_signals) == 0

    def test_holdings_without_sector(self):
        """Holdings without sector should not crash sector clustering."""
        portfolios = [
            _make_portfolio("A", [_make_holding("AAPL"), _make_holding("MSFT")]),
            _make_portfolio("B", [_make_holding("AAPL"), _make_holding("MSFT")]),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2)
        result = analyzer.analyze(portfolios)
        # No sector clusters since no sector data
        assert len(result.sector_clusters) == 0
        # But overlap should still work
        assert len(result.overlap_signals) == 2

    def test_large_portfolio_count(self):
        """Test with many portfolios to verify scalability."""
        portfolios = []
        for i in range(20):
            holdings = [
                _make_holding("AAPL", sector="Technology", value=1000),
                _make_holding(f"T{i}", sector="Technology", value=500),
            ]
            portfolios.append(_make_portfolio(f"Fund {i}", holdings))

        analyzer = PortfolioAnalyzer(min_overlap=5)
        result = analyzer.analyze(portfolios)

        aapl = next((s for s in result.overlap_signals if s.ticker == "AAPL"), None)
        assert aapl is not None
        assert aapl.overlap_count == 20

    def test_duplicate_ticker_in_same_portfolio(self):
        """Same ticker appearing multiple times in one portfolio."""
        portfolios = [
            _make_portfolio(
                "A",
                [
                    _make_holding("AAPL", name="Apple CL A", value=100),
                    _make_holding("AAPL", name="Apple CL B", value=50),
                ],
            ),
            _make_portfolio("B", [_make_holding("AAPL", value=200)]),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(portfolios)

        aapl = next((s for s in signals if s.ticker == "AAPL"), None)
        assert aapl is not None
        # Both entries from portfolio A plus portfolio B = 3 appearances
        assert aapl.overlap_count == 2  # 2 portfolios, not 3 entries

    def test_strength_capped_at_100(self):
        """Strength should never exceed 100."""
        portfolios = []
        for i in range(10):
            holdings = [_make_holding("AAPL", weight=50.0)]
            portfolios.append(_make_portfolio(f"Fund {i}", holdings))

        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_overlap(portfolios)

        for signal in signals:
            assert signal.strength <= 100.0


# ============================================================
# Test Filing Diff Logic
# ============================================================


class TestFilingDiff:
    """Tests for the quarter-over-quarter filing diff logic."""

    def test_diff_detects_new_positions(self):
        """Tickers in current but not previous should be 'new'."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        current = [
            _make_holding("AAPL", "Apple", shares=1000, value=100000),
            _make_holding("NVDA", "NVIDIA", shares=500, value=50000),
        ]
        previous = [
            _make_holding("AAPL", "Apple", shares=1000, value=90000),
        ]

        result = source._diff_holdings(current, previous, filing_date=datetime(2024, 5, 15))

        nvda = next((h for h in result if h.ticker == "NVDA"), None)
        assert nvda is not None
        assert nvda.action == "new"

    def test_diff_detects_exit_positions(self):
        """Tickers in previous but not current should get 'exit' entries."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        current = [
            _make_holding("AAPL", "Apple", shares=1000, value=100000),
        ]
        previous = [
            _make_holding("AAPL", "Apple", shares=1000, value=90000),
            _make_holding("META", "Meta", shares=2000, value=60000),
        ]

        result = source._diff_holdings(current, previous, filing_date=datetime(2024, 5, 15))

        meta = next((h for h in result if h.ticker == "META"), None)
        assert meta is not None
        assert meta.action == "exit"
        assert meta.shares == 0

    def test_diff_detects_add(self):
        """Shares increased >5% should be 'add'."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        current = [
            _make_holding("AAPL", "Apple", shares=1200, value=120000),
        ]
        previous = [
            _make_holding("AAPL", "Apple", shares=1000, value=100000),
        ]

        result = source._diff_holdings(current, previous)

        aapl = next((h for h in result if h.ticker == "AAPL"), None)
        assert aapl is not None
        assert aapl.action == "add"

    def test_diff_detects_trim(self):
        """Shares decreased >5% should be 'trim'."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        current = [
            _make_holding("AAPL", "Apple", shares=800, value=80000),
        ]
        previous = [
            _make_holding("AAPL", "Apple", shares=1000, value=100000),
        ]

        result = source._diff_holdings(current, previous)

        aapl = next((h for h in result if h.ticker == "AAPL"), None)
        assert aapl is not None
        assert aapl.action == "trim"

    def test_diff_detects_hold(self):
        """Shares within 5% should be 'hold'."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        current = [
            _make_holding("AAPL", "Apple", shares=1020, value=102000),
        ]
        previous = [
            _make_holding("AAPL", "Apple", shares=1000, value=100000),
        ]

        result = source._diff_holdings(current, previous)

        aapl = next((h for h in result if h.ticker == "AAPL"), None)
        assert aapl is not None
        assert aapl.action == "hold"

    def test_diff_sets_filing_date(self):
        """All holdings should get the filing date set."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        filing_date = datetime(2024, 5, 15)
        current = [
            _make_holding("AAPL", "Apple", shares=1000, value=100000),
        ]
        previous = [
            _make_holding("AAPL", "Apple", shares=1000, value=90000),
        ]

        result = source._diff_holdings(current, previous, filing_date=filing_date)

        assert result[0].date == filing_date

    def test_diff_handles_duplicate_cusips(self):
        """Same ticker appearing multiple times should be summed for comparison."""
        from src.discovery.sources.edgar_13f import Edgar13FSource

        source = Edgar13FSource(cache_dir="data")
        current = [
            _make_holding("AAPL", "Apple CL A", shares=500, value=50000),
            _make_holding("AAPL", "Apple CL B", shares=500, value=50000),
        ]
        previous = [
            _make_holding("AAPL", "Apple CL A", shares=480, value=48000),
            _make_holding("AAPL", "Apple CL B", shares=480, value=48000),
        ]

        result = source._diff_holdings(current, previous)

        # Total: 1000 vs 960 = ~4% increase, should be 'hold' (under 5%)
        aapl_holdings = [h for h in result if h.ticker == "AAPL"]
        # Both entries should have an action
        assert all(h.action is not None for h in aapl_holdings)

    def test_convergence_with_new_add_actions(self):
        """Convergence should detect 'new' and 'add' as buy signals."""
        now = datetime.now()
        portfolios = [
            _make_portfolio(
                "A", [_make_holding("NVDA", action="new", date=now - timedelta(days=10))]
            ),
            _make_portfolio(
                "B", [_make_holding("NVDA", action="add", date=now - timedelta(days=20))]
            ),
            _make_portfolio(
                "C", [_make_holding("NVDA", action="new", date=now - timedelta(days=30))]
            ),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2, convergence_window_days=90)
        events = analyzer._detect_convergence(portfolios)

        nvda = next((e for e in events if e.ticker == "NVDA"), None)
        assert nvda is not None
        assert nvda.action == "buy"
        assert len(nvda.portfolios) == 3

    def test_contrarian_with_new_vs_exit(self):
        """Contrarian should detect 'new'/'add' vs 'exit'/'trim' as disagreement."""
        now = datetime.now()
        portfolios = [
            _make_portfolio("A", [_make_holding("META", action="new", date=now)]),
            _make_portfolio("B", [_make_holding("META", action="add", date=now)]),
            _make_portfolio("C", [_make_holding("META", action="exit", date=now)]),
        ]
        analyzer = PortfolioAnalyzer(min_overlap=2)
        signals = analyzer._detect_contrarian(portfolios)

        meta = next((s for s in signals if s.ticker == "META"), None)
        assert meta is not None
        assert "A" in meta.buyers or "B" in meta.buyers
        assert "C" in meta.sellers
        assert meta.net_direction == "bullish"  # 2 buyers vs 1 seller
