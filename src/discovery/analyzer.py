"""
Cross-Portfolio Analyzer

Detects patterns across multiple tracked portfolios:
1. Ticker Overlap — tickers appearing in multiple portfolios (consensus picks)
2. Sector/Industry Clustering — granular concentration patterns
3. Activity Convergence — multiple portfolios acting on same ticker in a time window
4. Contrarian Signals — divergence between portfolio groups
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from .models import (
    ContrarianSignal,
    ConvergenceEvent,
    DiscoveryResult,
    DiscoverySignal,
    Holding,
    SectorCluster,
    TrackedPortfolio,
)

logger = logging.getLogger(__name__)


class PortfolioAnalyzer:
    """
    Analyzes multiple portfolios for cross-cutting patterns and signals.
    """

    def __init__(
        self,
        min_overlap: int = 2,
        convergence_window_days: int = 90,
        min_sector_holdings: int = 3,
    ):
        """
        Args:
            min_overlap: Minimum number of portfolios a ticker must appear in
                         to be considered an overlap signal.
            convergence_window_days: Time window (days) for activity convergence detection.
            min_sector_holdings: Minimum holdings in a sector/industry to form a cluster.
        """
        self.min_overlap = min_overlap
        self.convergence_window_days = convergence_window_days
        self.min_sector_holdings = min_sector_holdings

    def analyze(self, portfolios: list[TrackedPortfolio]) -> DiscoveryResult:
        """
        Run full cross-portfolio analysis.

        Args:
            portfolios: List of populated TrackedPortfolio objects.

        Returns:
            DiscoveryResult with all detected signals and patterns.
        """
        if not portfolios:
            return DiscoveryResult()

        total_holdings = sum(len(p.holdings) for p in portfolios)
        logger.info(f"Analyzing {len(portfolios)} portfolios with {total_holdings} total holdings")

        result = DiscoveryResult(
            portfolios_analyzed=len(portfolios),
            total_holdings=total_holdings,
        )

        # Run all analysis patterns
        result.overlap_signals = self._detect_overlap(portfolios)
        result.sector_clusters = self._detect_sector_clusters(portfolios)
        result.convergence_events = self._detect_convergence(portfolios)
        result.contrarian_signals = self._detect_contrarian(portfolios)

        logger.info(
            f"Found {len(result.overlap_signals)} overlap signals, "
            f"{len(result.sector_clusters)} sector clusters, "
            f"{len(result.convergence_events)} convergence events, "
            f"{len(result.contrarian_signals)} contrarian signals"
        )

        return result

    def _detect_overlap(self, portfolios: list[TrackedPortfolio]) -> list[DiscoverySignal]:
        """
        Detect tickers that appear in multiple portfolios.

        Strength is based on:
        - Number of portfolios holding the ticker (overlap count)
        - Average weight in those portfolios
        - Total value across all portfolios
        """
        # Map ticker → list of (portfolio_name, holding)
        ticker_appearances: dict[str, list[tuple[str, Holding]]] = defaultdict(list)

        for portfolio in portfolios:
            for holding in portfolio.holdings:
                ticker_appearances[holding.ticker].append((portfolio.name, holding))

        signals = []
        total_portfolios = len(portfolios)

        for ticker, appearances in ticker_appearances.items():
            # Count unique portfolios (not raw entries — same ticker can appear
            # multiple times in one portfolio, e.g. different share classes)
            unique_portfolios = list(dict.fromkeys(name for name, _ in appearances))
            overlap_count = len(unique_portfolios)
            if overlap_count < self.min_overlap:
                continue

            # Collect info from all appearances
            portfolio_names = unique_portfolios
            holdings = [h for _, h in appearances]

            # Use the first holding with sector info
            sector = next((h.sector for h in holdings if h.sector), None)
            industry = next((h.industry for h in holdings if h.industry), None)
            name = next((h.name for h in holdings if h.name), ticker)

            # Calculate strength (0-100)
            # Factors: overlap ratio (60%), average weight (20%), value signal (20%)
            overlap_ratio = overlap_count / total_portfolios
            avg_weight = self._safe_avg([h.weight for h in holdings if h.weight])
            weight_score = min(avg_weight / 5.0, 1.0) if avg_weight else 0.5  # 5% = max score

            strength = (overlap_ratio * 60) + (weight_score * 20) + (overlap_ratio * 20)
            strength = min(strength, 100.0)

            # Build recent actions descriptions
            recent_actions = []
            for pname, h in appearances:
                if h.action:
                    date_str = h.date.strftime("%Y-%m") if h.date else ""
                    recent_actions.append(f"{pname}: {h.action.upper()} {date_str}".strip())

            signals.append(
                DiscoverySignal(
                    ticker=ticker,
                    name=name,
                    sector=sector,
                    industry=industry,
                    signal_type="overlap",
                    strength=strength,
                    portfolios=portfolio_names,
                    overlap_count=overlap_count,
                    total_portfolios=total_portfolios,
                    recent_actions=recent_actions,
                )
            )

        # Sort by strength descending
        return sorted(signals, key=lambda s: s.strength, reverse=True)

    def _detect_sector_clusters(self, portfolios: list[TrackedPortfolio]) -> list[SectorCluster]:
        """
        Detect sector/industry concentration patterns across portfolios.

        Groups holdings by granular industry (not just top-level sector),
        identifies where multiple portfolios are concentrating.
        """
        # Group by (sector, industry) tuple
        industry_map: dict[tuple[str, Optional[str]], list[tuple[str, Holding]]] = defaultdict(list)

        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.sector:
                    key = (holding.sector, holding.industry)
                    industry_map[key].append((portfolio.name, holding))

        clusters = []

        for (sector, industry), appearances in industry_map.items():
            # Count unique tickers and portfolios
            tickers = list({h.ticker for _, h in appearances})
            portfolio_names = list({name for name, _ in appearances})
            holding_count = len(appearances)

            if holding_count < self.min_sector_holdings:
                continue

            # Calculate total value
            values = [h.value for _, h in appearances if h.value]
            total_value = sum(values) if values else None

            # Average weight
            weights = [h.weight for _, h in appearances if h.weight]
            weight_avg = self._safe_avg(weights)

            # Strength: combination of portfolio breadth and holding depth
            # How many different portfolios are invested in this industry?
            portfolio_breadth = len(portfolio_names) / len(portfolios)
            # How many holdings per portfolio in this industry?
            depth = holding_count / max(len(portfolio_names), 1)
            depth_score = min(depth / 3.0, 1.0)  # 3+ holdings per portfolio = max

            strength = (portfolio_breadth * 60) + (depth_score * 40)
            strength = min(strength, 100.0)

            clusters.append(
                SectorCluster(
                    sector=sector,
                    industry=industry,
                    tickers=tickers[:20],  # Limit to top 20 tickers
                    portfolios=portfolio_names,
                    total_value=total_value,
                    weight_avg=weight_avg,
                    holding_count=holding_count,
                    strength=strength,
                )
            )

        return sorted(clusters, key=lambda c: c.strength, reverse=True)

    def _detect_convergence(self, portfolios: list[TrackedPortfolio]) -> list[ConvergenceEvent]:
        """
        Detect multiple portfolios taking the same action on the same ticker
        within a configurable time window.

        This requires holdings to have action + date fields populated
        (most relevant for sources that provide transaction data like congressional trades).
        """
        # Group actions by ticker
        ticker_actions: dict[str, list[tuple[str, Holding]]] = defaultdict(list)

        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.action and holding.date:
                    ticker_actions[holding.ticker].append((portfolio.name, holding))

        events = []
        window = timedelta(days=self.convergence_window_days)

        for ticker, actions in ticker_actions.items():
            if len(actions) < self.min_overlap:
                continue

            # Group by action type (buy vs sell)
            buys = [(name, h) for name, h in actions if h.action in ("buy", "new", "add")]
            sells = [(name, h) for name, h in actions if h.action in ("sell", "exit", "trim")]

            # Check for buy convergence
            buy_event = self._find_convergence_window(ticker, "buy", buys, window)
            if buy_event:
                events.append(buy_event)

            # Check for sell convergence
            sell_event = self._find_convergence_window(ticker, "sell", sells, window)
            if sell_event:
                events.append(sell_event)

        return sorted(events, key=lambda e: e.strength, reverse=True)

    def _find_convergence_window(
        self,
        ticker: str,
        action: str,
        actions: list[tuple[str, Holding]],
        window: timedelta,
    ) -> Optional[ConvergenceEvent]:
        """Find the largest convergence cluster within a time window."""
        if len(actions) < self.min_overlap:
            return None

        # Sort by date
        sorted_actions = sorted(actions, key=lambda x: x[1].date or datetime.min)

        # Sliding window to find max convergence
        best_cluster: list[tuple[str, Holding]] = []

        for i, (name_i, h_i) in enumerate(sorted_actions):
            if not h_i.date:
                continue
            cluster = [(name_i, h_i)]
            for j in range(i + 1, len(sorted_actions)):
                name_j, h_j = sorted_actions[j]
                if not h_j.date:
                    continue
                if h_j.date - h_i.date <= window:
                    cluster.append((name_j, h_j))

            if len(cluster) > len(best_cluster):
                best_cluster = cluster

        if len(best_cluster) < self.min_overlap:
            return None

        portfolios = [name for name, _ in best_cluster]
        dates = [h.date for _, h in best_cluster if h.date]
        name = best_cluster[0][1].name if best_cluster else None

        # Strength based on number of convergent actors
        strength = min((len(best_cluster) / 4) * 100, 100.0)  # 4+ = max strength

        # Calculate actual window used
        if dates:
            actual_window = (max(dates) - min(dates)).days
        else:
            actual_window = self.convergence_window_days

        return ConvergenceEvent(
            ticker=ticker,
            name=name,
            action=action,
            portfolios=portfolios,
            dates=dates,
            window_days=actual_window,
            strength=strength,
        )

    def _detect_contrarian(self, portfolios: list[TrackedPortfolio]) -> list[ContrarianSignal]:
        """
        Detect tickers where some portfolios are buying while others are selling.

        This indicates disagreement among notable investors — potentially
        an opportunity if you side with the right group.
        """
        # Group holdings with actions by ticker
        ticker_actions: dict[str, list[tuple[str, Holding]]] = defaultdict(list)

        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.action:
                    ticker_actions[holding.ticker].append((portfolio.name, holding))

        signals = []

        for ticker, actions in ticker_actions.items():
            buyers = [name for name, h in actions if h.action in ("buy", "new", "add")]
            sellers = [name for name, h in actions if h.action in ("sell", "exit", "trim")]

            # Need at least one buyer AND one seller for a contrarian signal
            if not buyers or not sellers:
                continue

            name = next((h.name for _, h in actions if h.name), None)
            total_actors = len(buyers) + len(sellers)
            net_direction = "bullish" if len(buyers) > len(sellers) else "bearish"

            # Strength: how balanced is the disagreement? (more balanced = stronger signal)
            balance = min(len(buyers), len(sellers)) / max(len(buyers), len(sellers))
            volume = min(total_actors / 4, 1.0)  # More actors = stronger
            strength = (balance * 50) + (volume * 50)

            signals.append(
                ContrarianSignal(
                    ticker=ticker,
                    name=name,
                    buyers=buyers,
                    sellers=sellers,
                    net_direction=net_direction,
                    strength=strength,
                )
            )

        return sorted(signals, key=lambda s: s.strength, reverse=True)

    @staticmethod
    def _safe_avg(values: list[Optional[float]]) -> Optional[float]:
        """Calculate average of non-None values."""
        valid = [v for v in values if v is not None]
        return sum(valid) / len(valid) if valid else None
