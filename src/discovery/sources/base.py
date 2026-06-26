"""
Abstract base class for portfolio data sources.
"""

from abc import ABC, abstractmethod

from ..models import TrackedPortfolio


class PortfolioSource(ABC):
    """Abstract base for any portfolio data source (EDGAR, Quiver, etc.)."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source (e.g., 'edgar_13f', 'quiver')."""
        ...

    @abstractmethod
    def fetch_portfolios(self, use_cache: bool = True) -> list[TrackedPortfolio]:
        """
        Fetch all configured portfolios from this source.

        Args:
            use_cache: Whether to use cached data if available.

        Returns:
            List of TrackedPortfolio objects with holdings populated.
        """
        ...

    @abstractmethod
    def list_available(self) -> list[dict]:
        """
        List available portfolios/filers from this source.

        Returns:
            List of dicts with at minimum {"name": ..., "id": ...}
        """
        ...
