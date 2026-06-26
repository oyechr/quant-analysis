"""
CUSIP-to-ticker resolution and sector enrichment.

13F filings report holdings by CUSIP (a 9-character alphanumeric identifier).
This module resolves CUSIPs to ticker symbols and enriches holdings with
sector/industry data using yfinance.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import yfinance as yf

from ..models import Holding, TrackedPortfolio

logger = logging.getLogger(__name__)


class HoldingEnricher:
    """
    Resolves CUSIP identifiers to ticker symbols and enriches holdings
    with sector/industry classification from yfinance.
    """

    def __init__(self, cache_dir: str = "data"):
        self.cache_dir = Path(cache_dir) / "_discovery" / "enrichment"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cusip_cache_file = self.cache_dir / "cusip_map.json"
        self._sector_cache_file = self.cache_dir / "sector_map.json"
        self._cusip_map: dict[str, str] = self._load_cusip_cache()
        self._sector_map: dict[str, dict] = self._load_sector_cache()

    def _load_cusip_cache(self) -> dict[str, str]:
        """Load CUSIP→ticker mapping cache."""
        if self._cusip_cache_file.exists():
            try:
                return json.loads(self._cusip_cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _load_sector_cache(self) -> dict[str, dict]:
        """Load ticker→sector/industry mapping cache."""
        if self._sector_cache_file.exists():
            try:
                return json.loads(self._sector_cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_cusip_cache(self):
        """Persist CUSIP map to disk."""
        try:
            self._cusip_cache_file.write_text(
                json.dumps(self._cusip_map, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.warning(f"Failed to save CUSIP cache: {e}")

    def _save_sector_cache(self):
        """Persist sector map to disk."""
        try:
            self._sector_cache_file.write_text(
                json.dumps(self._sector_map, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.warning(f"Failed to save sector cache: {e}")

    def enrich_portfolio(self, portfolio: TrackedPortfolio) -> TrackedPortfolio:
        """
        Enrich all holdings in a portfolio with ticker symbols and sector data.

        Modifies holdings in-place and returns the portfolio.
        """
        total_value = portfolio.total_value

        for holding in portfolio.holdings:
            # Try to resolve CUSIP to ticker
            resolved_ticker = self._resolve_ticker(holding)
            if resolved_ticker:
                holding.ticker = resolved_ticker

            # Enrich with sector/industry
            self._enrich_sector(holding)

            # Calculate portfolio weight
            if total_value and holding.value:
                holding.weight = (holding.value / total_value) * 100

        # Save caches after batch enrichment
        self._save_cusip_cache()
        self._save_sector_cache()

        return portfolio

    def _resolve_ticker(self, holding: Holding) -> Optional[str]:
        """
        Attempt to resolve a CUSIP to a ticker symbol.

        Strategy:
        1. Check cache
        2. Use the issuer name to search via yfinance
        """
        cusip = holding.ticker  # Initially stored as CUSIP

        # Check cache
        if cusip in self._cusip_map:
            return self._cusip_map[cusip]

        # Try to find ticker by company name via yfinance search
        ticker = self._search_ticker_by_name(holding.name)
        if ticker:
            self._cusip_map[cusip] = ticker
            return ticker

        # If name looks like a ticker already (short, all caps), keep it
        if len(cusip) <= 5 and cusip.isalpha():
            return cusip

        return None

    def _search_ticker_by_name(self, name: str) -> Optional[str]:
        """Search for a ticker symbol by company name using yfinance."""
        if not name:
            return None

        # Clean up common suffixes in 13F filings
        search_name = name.upper()
        for suffix in [" INC", " CORP", " LTD", " PLC", " CO", " CL A", " CL B", " COM", " NEW"]:
            search_name = search_name.replace(suffix, "")
        search_name = search_name.strip()

        if not search_name:
            return None

        try:
            # yfinance doesn't have a great search API, but we can try
            # using the Ticker object with common patterns
            # First, try the name as-is (some names ARE tickers)
            if len(search_name) <= 5 and search_name.isalpha():
                ticker_obj = yf.Ticker(search_name)
                info = ticker_obj.info
                if info and len(info) > 5:
                    return search_name
        except Exception:
            pass

        return None

    def _enrich_sector(self, holding: Holding):
        """Add sector/industry data to a holding from yfinance."""
        ticker = holding.ticker
        if not ticker or len(ticker) > 10:
            return

        # Check sector cache
        if ticker in self._sector_map:
            cached = self._sector_map[ticker]
            holding.sector = cached.get("sector")
            holding.industry = cached.get("industry")
            return

        # Fetch from yfinance
        try:
            info = yf.Ticker(ticker).info
            if info and len(info) > 5:
                sector = info.get("sector")
                industry = info.get("industry")
                if sector and sector != "N/A":
                    holding.sector = sector
                    holding.industry = industry
                    self._sector_map[ticker] = {"sector": sector, "industry": industry}
        except Exception as e:
            logger.debug(f"Failed to get sector for {ticker}: {e}")

    def enrich_tickers_in_portfolios(
        self, portfolios: list[TrackedPortfolio], tickers: set[str]
    ) -> None:
        """
        Enrich only specific tickers across all portfolios with sector/industry data.

        This is much faster than enriching ALL holdings — typically used to
        enrich just the top overlap results (20-50 tickers vs 800+).

        Args:
            portfolios: List of portfolios to update in-place.
            tickers: Set of ticker identifiers to enrich.
        """
        enriched_count = 0
        # Only fetch sector data for tickers we haven't cached yet
        tickers_to_fetch = {t for t in tickers if t not in self._sector_map}
        logger.info(
            f"Enriching {len(tickers)} tickers ({len(tickers_to_fetch)} uncached)"
        )

        for ticker in tickers_to_fetch:
            # Skip things that look like CUSIPs (9 chars, alphanumeric)
            if len(ticker) == 9 and ticker[:6].isalpha():
                continue
            try:
                info = yf.Ticker(ticker).info
                if info and len(info) > 5:
                    sector = info.get("sector")
                    industry = info.get("industry")
                    if sector and sector != "N/A":
                        self._sector_map[ticker] = {"sector": sector, "industry": industry}
                        enriched_count += 1
                    else:
                        # Cache as unknown to avoid re-fetching
                        self._sector_map[ticker] = {"sector": None, "industry": None}
                else:
                    self._sector_map[ticker] = {"sector": None, "industry": None}
            except Exception as e:
                logger.debug(f"Failed to enrich {ticker}: {e}")
                self._sector_map[ticker] = {"sector": None, "industry": None}

        # Now apply cached sector data to all holdings with matching tickers
        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.ticker in tickers and holding.ticker in self._sector_map:
                    cached = self._sector_map[holding.ticker]
                    holding.sector = cached.get("sector")
                    holding.industry = cached.get("industry")

        self._save_sector_cache()
        logger.info(f"Enriched {enriched_count} tickers with sector/industry data")
