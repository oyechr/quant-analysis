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

from .models import Holding, TrackedPortfolio

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
        """Search for a ticker symbol by company name using yfinance Search."""
        if not name:
            return None

        # Clean up common suffixes in 13F filings (strip from end only)
        search_name = name.upper().strip()
        changed = True
        while changed:
            changed = False
            for suffix in [
                " INC",
                " CORP",
                " LTD",
                " PLC",
                " CO",
                " CL A",
                " CL B",
                " COM",
                " NEW",
                " CLASS A",
                " CLASS B",
                " CLASS C",
                " HOLDINGS",
                " GROUP",
                " TECHNOLOGIES",
                " TECHNOLOGY",
                " INTERNATIONAL",
                " SYSTEMS",
                " PLATFORMS",
                " SOLUTIONS",
                " INCORPORATED",
                " DEL",
            ]:
                if search_name.endswith(suffix):
                    search_name = search_name[: -len(suffix)]
                    changed = True
                    break
        search_name = search_name.strip()

        # Expand common SEC filing abbreviations
        abbreviations = {
            "FINL": "FINANCIAL",
            "INTL": "INTERNATIONAL",
            "MGMT": "MANAGEMENT",
            "SVCS": "SERVICES",
            "HLDGS": "HOLDINGS",
            "BANCORP": "BANK",
            "SVC": "SERVICE",
            "TECHNOLOGES": "TECHNOLOGIES",
            "MTN BE": "",
        }
        for abbr, full in abbreviations.items():
            search_name = search_name.replace(abbr, full)
        search_name = " ".join(search_name.split())  # normalize whitespace

        if not search_name:
            return None

        try:
            from yfinance import Search

            results = Search(search_name, max_results=5)
            if results.quotes:
                for quote in results.quotes:
                    symbol = quote.get("symbol", "")
                    quote_type = quote.get("quoteType", "")
                    # Prefer US-listed equities without dots (no foreign tickers)
                    if symbol and "." not in symbol and quote_type == "EQUITY":
                        # Also cache sector/industry from search results
                        sector = quote.get("sector")
                        industry = quote.get("industry")
                        if sector:
                            self._sector_map[symbol] = {"sector": sector, "industry": industry}
                        return symbol
                # Fallback: first equity result even if foreign
                for quote in results.quotes:
                    symbol = quote.get("symbol", "")
                    if symbol and quote.get("quoteType") == "EQUITY":
                        sector = quote.get("sector")
                        industry = quote.get("industry")
                        if sector:
                            self._sector_map[symbol] = {"sector": sector, "industry": industry}
                        return symbol
        except Exception as e:
            logger.debug(f"Search failed for '{search_name}': {e}")

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

    def _is_cusip(self, identifier: str) -> bool:
        """Check if an identifier looks like a CUSIP (9 chars, has digits)."""
        return (
            len(identifier) == 9 and identifier.isalnum() and any(c.isdigit() for c in identifier)
        )

    def enrich_tickers_in_portfolios(
        self, portfolios: list[TrackedPortfolio], tickers: set[str]
    ) -> None:
        """
        Enrich only specific tickers across all portfolios with sector/industry data.

        For CUSIPs (from 13F filings), first resolves to real ticker symbols
        using the issuer name, then fetches sector/industry from yfinance.

        Args:
            portfolios: List of portfolios to update in-place.
            tickers: Set of ticker identifiers to enrich.
        """
        enriched_count = 0

        # Build a name lookup: CUSIP → issuer name (from holdings)
        cusip_to_name: dict[str, str] = {}
        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.ticker in tickers and holding.name:
                    cusip_to_name[holding.ticker] = holding.name

        # Step 1: Resolve CUSIPs to real tickers
        resolved_map: dict[str, str] = {}  # CUSIP → real ticker
        for identifier in tickers:
            if self._is_cusip(identifier):
                # Check CUSIP cache first
                if identifier in self._cusip_map:
                    resolved_map[identifier] = self._cusip_map[identifier]
                else:
                    # Try to resolve using issuer name
                    name = cusip_to_name.get(identifier)
                    if name:
                        real_ticker = self._search_ticker_by_name(name)
                        if real_ticker:
                            self._cusip_map[identifier] = real_ticker
                            resolved_map[identifier] = real_ticker
                            logger.debug(f"Resolved {identifier} ({name}) → {real_ticker}")
                        else:
                            # Cache as unresolvable
                            self._cusip_map[identifier] = identifier
                            logger.debug(f"Could not resolve {identifier} ({name})")
            else:
                # Already a ticker symbol
                resolved_map[identifier] = identifier

        self._save_cusip_cache()

        # Step 2: Fetch sector data for resolved tickers
        real_tickers = set(resolved_map.values())
        tickers_to_fetch = {
            t for t in real_tickers if t not in self._sector_map and not self._is_cusip(t)
        }
        logger.info(
            f"Enriching {len(tickers)} identifiers → {len(real_tickers)} unique tickers "
            f"({len(tickers_to_fetch)} need yfinance lookup)"
        )

        for ticker in tickers_to_fetch:
            try:
                info = yf.Ticker(ticker).info
                if info and len(info) > 5:
                    sector = info.get("sector")
                    industry = info.get("industry")
                    if sector and sector != "N/A":
                        self._sector_map[ticker] = {"sector": sector, "industry": industry}
                        enriched_count += 1
                    else:
                        self._sector_map[ticker] = {"sector": None, "industry": None}
                else:
                    self._sector_map[ticker] = {"sector": None, "industry": None}
            except Exception as e:
                logger.debug(f"Failed to enrich {ticker}: {e}")
                self._sector_map[ticker] = {"sector": None, "industry": None}

        # Step 3: Apply sector data back to holdings (using CUSIP → ticker → sector)
        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.ticker in tickers:
                    real_ticker = resolved_map.get(holding.ticker, holding.ticker)
                    if real_ticker in self._sector_map:
                        cached = self._sector_map[real_ticker]
                        holding.sector = cached.get("sector")
                        holding.industry = cached.get("industry")
                    # Also update the ticker to the real symbol for display
                    if real_ticker != holding.ticker and not self._is_cusip(real_ticker):
                        holding.ticker = real_ticker

        self._save_sector_cache()
        logger.info(f"Enriched {enriched_count} tickers with sector/industry data")
