"""
Portfolio Discovery Module

Discovers investment signals by analyzing notable portfolios (institutional 13F filings,
congressional trades, etc.) for patterns: ticker overlap, sector clustering,
activity convergence, and contrarian signals.
"""

from .analyzer import PortfolioAnalyzer
from .models import DiscoverySignal, Holding, SectorCluster, TrackedPortfolio

__all__ = [
    "PortfolioAnalyzer",
    "DiscoverySignal",
    "Holding",
    "SectorCluster",
    "TrackedPortfolio",
]
