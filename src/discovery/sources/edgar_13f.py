"""
SEC EDGAR 13F Filing Source

Fetches institutional investor holdings from SEC EDGAR 13F-HR filings.
These are quarterly filings required for institutional managers with >$100M AUM.

API docs: https://www.sec.gov/search-filings
Rate limit: 10 requests/second with User-Agent header.

Notable filers (CIK numbers):
- Berkshire Hathaway: 0001067983
- ARK Investment Management: 0001697748
- Bridgewater Associates: 0001350694
- Soros Fund Management: 0001029160
- Renaissance Technologies: 0001037389
- Citadel Advisors: 0001423053
- Two Sigma Investments: 0001179392
- Pershing Square Capital: 0001336528
"""

import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from ..models import Holding, TrackedPortfolio
from .base import PortfolioSource

logger = logging.getLogger(__name__)

# Default notable institutional investors to track
NOTABLE_FILERS = [
    {
        "name": "Berkshire Hathaway",
        "cik": "0001067983",
        "description": "Warren Buffett's conglomerate",
    },
    {
        "name": "ARK Investment Management",
        "cik": "0001697748",
        "description": "Cathie Wood's innovation-focused fund",
    },
    {
        "name": "Soros Fund Management",
        "cik": "0001029160",
        "description": "George Soros' family office",
    },
    {
        "name": "Bridgewater Associates",
        "cik": "0001350694",
        "description": "Ray Dalio's macro hedge fund",
    },
    {
        "name": "Renaissance Technologies",
        "cik": "0001037389",
        "description": "Jim Simons' quant fund",
    },
    {
        "name": "Pershing Square Capital",
        "cik": "0001336528",
        "description": "Bill Ackman's activist fund",
    },
    {
        "name": "Appaloosa Management",
        "cik": "0001656456",
        "description": "David Tepper's hedge fund",
    },
    {
        "name": "Icahn Enterprises",
        "cik": "0000813762",
        "description": "Carl Icahn's investment vehicle",
    },
]

# EDGAR API constants
EDGAR_BASE_URL = "https://efts.sec.gov/LATEST"
EDGAR_FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# 13F information table XML namespace
NS_13F = {"ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}


class Edgar13FSource(PortfolioSource):
    """
    Fetches portfolio holdings from SEC EDGAR 13F-HR filings.

    13F filings are quarterly disclosures of equity holdings by institutional
    investment managers with >=100M USD in qualifying assets.
    """

    def __init__(
        self,
        filers: Optional[list[dict]] = None,
        cache_dir: str = "data",
        user_agent: Optional[str] = None,
    ):
        """
        Args:
            filers: List of filer dicts with "name" and "cik" keys.
                    Defaults to NOTABLE_FILERS.
            cache_dir: Directory for caching fetched filings.
            user_agent: Required by SEC EDGAR (company/email format).
                        Reads from config.json "edgar_user_agent" if not set.
        """
        from ...config import get_config

        self.filers = filers or NOTABLE_FILERS
        self.cache_dir = Path(cache_dir) / "_discovery" / "edgar_13f"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or get_config().edgar_user_agent
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json"})
        self._last_request_time = 0.0

    @property
    def source_name(self) -> str:
        return "edgar_13f"

    def _rate_limit(self):
        """Enforce 10 req/sec rate limit for EDGAR."""
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.12:  # ~8 req/sec to stay safe
            time.sleep(0.12 - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET request to EDGAR."""
        self._rate_limit()
        response = self._session.get(url, timeout=30, **kwargs)
        response.raise_for_status()
        return response

    def list_available(self) -> list[dict]:
        """List the configured notable filers."""
        return [
            {"name": f["name"], "id": f["cik"], "description": f.get("description", "")}
            for f in self.filers
        ]

    def fetch_portfolios(self, use_cache: bool = True) -> list[TrackedPortfolio]:
        """
        Fetch latest 13F holdings for all configured filers.
        Compares against previous quarter to infer buy/sell actions.

        Args:
            use_cache: Use cached filing data if available.

        Returns:
            List of TrackedPortfolio with holdings populated (including inferred actions).
        """
        portfolios = []
        for filer in self.filers:
            try:
                portfolio = self._fetch_filer_portfolio_with_diff(
                    name=filer["name"],
                    cik=filer["cik"],
                    use_cache=use_cache,
                )
                if portfolio and portfolio.holdings:
                    portfolios.append(portfolio)
                    logger.info(f"Fetched {len(portfolio.holdings)} holdings for {filer['name']}")
                else:
                    logger.warning(f"No holdings found for {filer['name']}")
            except Exception as e:
                logger.warning(f"Failed to fetch {filer['name']} (CIK {filer['cik']}): {e}")
                continue
        return portfolios

    def _fetch_filer_portfolio_with_diff(
        self, name: str, cik: str, use_cache: bool = True
    ) -> Optional[TrackedPortfolio]:
        """
        Fetch the 2 most recent 13F filings, diff them to infer actions.

        Actions inferred:
        - "new": ticker in current but not in previous
        - "exit": ticker in previous but not in current
        - "add": shares increased
        - "trim": shares decreased
        - "hold": shares unchanged
        """
        cache_file = self.cache_dir / f"{cik}.json"

        # Check cache
        if use_cache and cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return self._deserialize_portfolio(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Cache corrupt for {name}, re-fetching: {e}")

        # Fetch the two most recent 13F filings
        filings = self._get_recent_13f_filings(cik, count=2)
        if not filings:
            return None

        # Parse current (latest) filing
        current_filing = filings[0]
        current_holdings = self._parse_information_table(current_filing["info_table_url"])
        if not current_holdings:
            return None

        # Parse previous filing (if available) and diff
        if len(filings) >= 2:
            previous_filing = filings[1]
            previous_holdings = self._parse_information_table(previous_filing["info_table_url"])
            if previous_holdings:
                current_holdings = self._diff_holdings(
                    current_holdings,
                    previous_holdings,
                    filing_date=current_filing.get("filing_date"),
                )

        portfolio = TrackedPortfolio(
            name=name,
            source=self.source_name,
            holdings=current_holdings,
            cik=cik,
            filing_date=current_filing.get("filing_date"),
            period_of_report=current_filing.get("period_of_report"),
        )

        # Cache the result
        try:
            cache_file.write_text(
                json.dumps(self._serialize_portfolio(portfolio), indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning(f"Failed to cache portfolio for {name}: {e}")

        return portfolio

    def _diff_holdings(
        self,
        current: list[Holding],
        previous: list[Holding],
        filing_date: Optional[datetime] = None,
    ) -> list[Holding]:
        """
        Compare current vs previous holdings to infer buy/sell actions.

        Returns current holdings with action and date fields populated.
        Also appends "exit" holdings for positions that were sold entirely.
        """
        # Build lookup: ticker → holding for previous
        prev_map: dict[str, Holding] = {}
        for h in previous:
            # If same ticker appears multiple times, sum shares
            if h.ticker in prev_map:
                existing = prev_map[h.ticker]
                if existing.shares and h.shares:
                    existing.shares += h.shares
                if existing.value and h.value:
                    existing.value += h.value
            else:
                prev_map[h.ticker] = h

        # Build lookup for current (to detect duplicates)
        curr_map: dict[str, Holding] = {}
        for h in current:
            if h.ticker in curr_map:
                existing = curr_map[h.ticker]
                if existing.shares and h.shares:
                    existing.shares += h.shares
                if existing.value and h.value:
                    existing.value += h.value
            else:
                curr_map[h.ticker] = h

        # Annotate current holdings with actions
        for h in current:
            h.date = filing_date
            if h.ticker not in prev_map:
                h.action = "new"
            else:
                prev_h = prev_map[h.ticker]
                curr_h = curr_map[h.ticker]
                if curr_h.shares and prev_h.shares:
                    change_pct = (curr_h.shares - prev_h.shares) / prev_h.shares
                    if change_pct > 0.05:  # >5% increase
                        h.action = "add"
                    elif change_pct < -0.05:  # >5% decrease
                        h.action = "trim"
                    else:
                        h.action = "hold"
                else:
                    h.action = "hold"

        # Add "exit" entries for positions completely sold
        current_tickers = {h.ticker for h in current}
        for ticker, prev_h in prev_map.items():
            if ticker not in current_tickers:
                exit_holding = Holding(
                    ticker=ticker,
                    name=prev_h.name,
                    shares=0,
                    value=0,
                    sector=prev_h.sector,
                    industry=prev_h.industry,
                    action="exit",
                    date=filing_date,
                )
                current.append(exit_holding)

        return current

    def _get_recent_13f_filings(self, cik: str, count: int = 2) -> list[dict]:
        """
        Find the N most recent 13F-HR filings for a CIK.

        Returns list of filing info dicts (newest first), each with:
        - info_table_url: URL to the information table XML
        - filing_date: datetime
        - period_of_report: datetime
        """
        cik_padded = cik.lstrip("0").zfill(10)
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

        try:
            response = self._get(submissions_url)
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch submissions for CIK {cik}: {e}")
            return []

        recent_filings = data.get("filings", {}).get("recent", {})
        forms = recent_filings.get("form", [])
        accession_numbers = recent_filings.get("accessionNumber", [])
        filing_dates = recent_filings.get("filingDate", [])
        report_dates = recent_filings.get("reportDate", [])

        results = []
        for i, form in enumerate(forms):
            if form in ("13F-HR", "13F-HR/A"):
                accession = accession_numbers[i].replace("-", "")
                filing_date_str = filing_dates[i] if i < len(filing_dates) else None
                report_date_str = report_dates[i] if i < len(report_dates) else None

                info_table_url = self._find_info_table_url(cik_padded, accession)
                if not info_table_url:
                    continue

                result = {"info_table_url": info_table_url}
                if filing_date_str:
                    try:
                        result["filing_date"] = datetime.strptime(filing_date_str, "%Y-%m-%d")
                    except ValueError:
                        pass
                if report_date_str:
                    try:
                        result["period_of_report"] = datetime.strptime(report_date_str, "%Y-%m-%d")
                    except ValueError:
                        pass

                results.append(result)
                if len(results) >= count:
                    break

        return results

    def _find_info_table_url(self, cik_padded: str, accession: str) -> Optional[str]:
        """
        Find the information table XML URL within a filing.

        Checks the filing index for a file matching the infotable pattern.
        """
        # Filing index JSON endpoint
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_padded.lstrip('0')}/{accession}/index.json"
        )

        try:
            response = self._get(index_url)
            index_data = response.json()
        except Exception as e:
            logger.debug(f"Failed to fetch filing index: {e}")
            return None

        # Look for the information table file
        directory = index_data.get("directory", {})
        items = directory.get("item", [])

        for item in items:
            name = item.get("name", "").lower()
            if "infotable" in name and name.endswith(".xml"):
                cik_stripped = cik_padded.lstrip("0")
                return (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik_stripped}/{accession}/{item['name']}"
                )

        # Fallback: look for any XML file that might be the info table
        for item in items:
            name = item.get("name", "").lower()
            if name.endswith(".xml") and "primary" not in name:
                cik_stripped = cik_padded.lstrip("0")
                return (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik_stripped}/{accession}/{item['name']}"
                )

        return None

    def _parse_information_table(self, url: str) -> list[Holding]:
        """
        Parse a 13F information table XML into Holding objects.

        The XML schema uses namespace:
        http://www.sec.gov/edgar/document/thirteenf/informationtable
        """
        try:
            response = self._get(url)
            content = response.content
        except Exception as e:
            logger.error(f"Failed to fetch information table: {e}")
            return []

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            logger.error(f"Failed to parse information table XML: {e}")
            return []

        holdings = []

        # Find all infoTable entries — try both namespaced and non-namespaced
        entries = root.findall(".//ns:infoTable", NS_13F)
        if not entries:
            # Try without namespace
            entries = root.findall(".//{*}infoTable")
        if not entries:
            # Try plain tags
            entries = root.findall(".//infoTable")

        for entry in entries:
            holding = self._parse_info_table_entry(entry)
            if holding:
                holdings.append(holding)

        return holdings

    def _parse_info_table_entry(self, entry: ET.Element) -> Optional[Holding]:
        """Parse a single 13F information table entry into a Holding."""

        def _find_text(element: ET.Element, tag: str) -> Optional[str]:
            """Find text in element, trying namespaced and non-namespaced."""
            # Try with namespace
            el = element.find(f"ns:{tag}", NS_13F)
            if el is not None and el.text:
                return el.text.strip()
            # Try wildcard namespace
            el = element.find(f"{{*}}{tag}")
            if el is not None and el.text:
                return el.text.strip()
            # Try plain
            el = element.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            return None

        def _find_nested_text(element: ET.Element, parent: str, child: str) -> Optional[str]:
            """Find text in nested element."""
            for ns_prefix in [f"ns:{parent}", f"{{*}}{parent}", parent]:
                try:
                    parent_el = (
                        element.find(ns_prefix, NS_13F)
                        if "ns:" in ns_prefix
                        else element.find(ns_prefix)
                    )
                except Exception:
                    parent_el = None
                if parent_el is None:
                    parent_el = element.find(f"{{*}}{parent}")
                if parent_el is not None:
                    text = _find_text(parent_el, child)
                    if text:
                        return text
            return None

        name = _find_text(entry, "nameOfIssuer")
        cusip = _find_text(entry, "cusip")
        value_str = _find_text(entry, "value")  # In thousands of USD
        shares_str = _find_nested_text(entry, "shrsOrPrnAmt", "sshPrnamt")

        if not name:
            return None

        # Convert value (reported in thousands)
        value = None
        if value_str:
            try:
                value = float(value_str) * 1000  # Convert from thousands to USD
            except ValueError:
                pass

        shares = None
        if shares_str:
            try:
                shares = float(shares_str)
            except ValueError:
                pass

        # 13F filings use CUSIP, not ticker. We'll need to resolve later.
        # For now, store CUSIP in ticker field — the enrichment step maps CUSIP→ticker.
        ticker = cusip or name.upper().replace(" ", ".")[:10]

        return Holding(
            ticker=ticker,
            name=name,
            shares=shares,
            value=value,
        )

    def _serialize_portfolio(self, portfolio: TrackedPortfolio) -> dict:
        """Serialize a TrackedPortfolio for JSON caching."""
        return {
            "name": portfolio.name,
            "source": portfolio.source,
            "cik": portfolio.cik,
            "filing_date": portfolio.filing_date.isoformat() if portfolio.filing_date else None,
            "period_of_report": (
                portfolio.period_of_report.isoformat() if portfolio.period_of_report else None
            ),
            "holdings": [
                {
                    "ticker": h.ticker,
                    "name": h.name,
                    "shares": h.shares,
                    "value": h.value,
                    "sector": h.sector,
                    "industry": h.industry,
                    "weight": h.weight,
                    "action": h.action,
                    "date": h.date.isoformat() if h.date else None,
                }
                for h in portfolio.holdings
            ],
        }

    def _deserialize_portfolio(self, data: dict) -> TrackedPortfolio:
        """Deserialize a TrackedPortfolio from cached JSON."""
        holdings = []
        for h in data.get("holdings", []):
            h_date = None
            if h.get("date"):
                try:
                    h_date = datetime.fromisoformat(h["date"])
                except ValueError:
                    pass
            holdings.append(
                Holding(
                    ticker=h["ticker"],
                    name=h["name"],
                    shares=h.get("shares"),
                    value=h.get("value"),
                    sector=h.get("sector"),
                    industry=h.get("industry"),
                    weight=h.get("weight"),
                    action=h.get("action"),
                    date=h_date,
                )
            )

        filing_date = None
        if data.get("filing_date"):
            try:
                filing_date = datetime.fromisoformat(data["filing_date"])
            except ValueError:
                pass

        period_of_report = None
        if data.get("period_of_report"):
            try:
                period_of_report = datetime.fromisoformat(data["period_of_report"])
            except ValueError:
                pass

        return TrackedPortfolio(
            name=data["name"],
            source=data.get("source", "edgar_13f"),
            holdings=holdings,
            cik=data.get("cik"),
            filing_date=filing_date,
            period_of_report=period_of_report,
        )
