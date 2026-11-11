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

How a quarter's holdings are built: the latest complete filing for the
report date (the original 13F-HR, or a 13F-HR/A of type RESTATEMENT, which
replaces it), plus any later 13F-HR/A of type NEW HOLDINGS (which only lists
positions left out of the original). Rows are summed per CUSIP, since a
filer lists one CUSIP once per manager or discretion type. Option rows
(putCall) and principal-amount rows (bonds, `sshPrnamtType` PRN) are left
out: they are not long stock.
"""

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ...utils.files import atomic_write_text
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
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# 13F information table XML namespace
NS_13F = {"ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}

FORM_13F = "13F-HR"
FORM_13F_AMENDMENT = "13F-HR/A"
RESTATEMENT = "RESTATEMENT"
NEW_HOLDINGS = "NEW HOLDINGS"

# A change in shares under this fraction is a "hold"
ACTION_THRESHOLD = 0.05
# A cache younger than this is used without asking EDGAR. After that, the
# filing list is checked (one request) and the holdings are refetched only
# when a filing was added or amended.
CACHE_CHECK_HOURS = 24
CACHE_VERSION = 2

# Polite pacing (SEC allows 10 requests/second) and retries for 429/5xx
MIN_REQUEST_INTERVAL = 0.12
RETRY = Retry(
    total=3,
    backoff_factor=1.0,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)


@dataclass(frozen=True)
class Filing:
    """One 13F-HR or 13F-HR/A entry from a filer's submission list."""

    form: str
    accession: str  # without dashes
    filing_date: Optional[datetime]
    report_date: Optional[datetime]


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
        from ...config import DEFAULT_EDGAR_USER_AGENT, get_config

        self.filers = filers or NOTABLE_FILERS
        self.cache_dir = Path(cache_dir) / "_discovery" / "edgar_13f"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or get_config().edgar_user_agent
        self._default_user_agent = self.user_agent == DEFAULT_EDGAR_USER_AGENT
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json"})
        adapter = HTTPAdapter(max_retries=RETRY)
        self._session.mount("https://", adapter)
        self._last_request_time = 0.0

    @property
    def source_name(self) -> str:
        return "edgar_13f"

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        """Rate-limited GET request to EDGAR (retried on 429 and 5xx)."""
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
        Latest 13F holdings for every configured filer, with the action
        (new/add/trim/hold/exit) inferred from the quarter before.
        """
        if self._default_user_agent:
            logger.warning(
                "SEC asks for a real contact in the User-Agent and may block the default. "
                'Set "edgar_user_agent": "Your Name your@email" in config.json.'
            )
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

    # ==================== Cache ====================

    def _read_cache(self, cache_file: Path) -> Optional[dict]:
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Cache unreadable, re-fetching: {cache_file} ({e})")
            return None
        return data if isinstance(data, dict) else None

    def _write_cache(self, cache_file: Path, portfolio: TrackedPortfolio) -> None:
        try:
            atomic_write_text(
                cache_file, json.dumps(self._serialize_portfolio(portfolio), indent=2)
            )
        except OSError as e:
            logger.warning(f"Failed to cache portfolio for {portfolio.name}: {e}")

    @staticmethod
    def _cache_is_recent(data: dict, now: datetime) -> bool:
        if data.get("cache_version") != CACHE_VERSION:
            return False
        try:
            fetched_at = datetime.fromisoformat(str(data.get("fetched_at")))
        except ValueError:
            return False
        return now - fetched_at < timedelta(hours=CACHE_CHECK_HOURS)

    # ==================== Fetch ====================

    def _fetch_filer_portfolio_with_diff(
        self, name: str, cik: str, use_cache: bool = True
    ) -> Optional[TrackedPortfolio]:
        """
        The latest quarter's holdings, diffed against the quarter before.

        Actions: "new" (not held last quarter), "exit" (held last quarter,
        not now; added as a placeholder with zero shares), "add" / "trim"
        (shares up / down by more than ACTION_THRESHOLD), else "hold".
        """
        cache_file = self.cache_dir / f"{cik}.json"
        cached = self._read_cache(cache_file) if use_cache else None
        now = datetime.now()
        if cached is not None and self._cache_is_recent(cached, now):
            return self._deserialize_portfolio(cached)

        try:
            filings = self._list_13f_filings(cik)
        except Exception as e:
            if cached is not None:
                logger.warning(f"Could not check EDGAR for {name}, using the cached filing: {e}")
                return self._deserialize_portfolio(cached)
            raise

        periods = latest_periods(filings, count=2)
        if not periods:
            return None
        accessions = sorted(f.accession for period in periods for f in period)

        if (
            cached is not None
            and cached.get("cache_version") == CACHE_VERSION
            and sorted(cached.get("accessions") or []) == accessions
        ):
            portfolio = self._deserialize_portfolio(cached)
            self._write_cache(cache_file, portfolio)  # stamps a new fetched_at
            return portfolio

        cik_padded = cik.lstrip("0").zfill(10)
        resolved = []
        for period in periods:
            holdings, base = self._period_holdings(cik_padded, period)
            if base is not None:
                resolved.append((holdings, base))
        if not resolved or not resolved[0][0]:
            if cached is not None:
                logger.warning(f"Could not read {name}'s latest 13F, using the cached filing")
                return self._deserialize_portfolio(cached)
            return None

        current, current_filing = resolved[0]
        if len(resolved) > 1 and resolved[1][0]:
            current = diff_holdings(current, resolved[1][0], filing_date=current_filing.filing_date)
        set_weights(current)

        portfolio = TrackedPortfolio(
            name=name,
            source=self.source_name,
            holdings=current,
            cik=cik,
            filing_date=current_filing.filing_date,
            period_of_report=current_filing.report_date,
            accessions=accessions,
        )
        self._write_cache(cache_file, portfolio)
        return portfolio

    def _list_13f_filings(self, cik: str) -> list[Filing]:
        """Every 13F-HR and 13F-HR/A in the filer's recent submissions."""
        cik_padded = cik.lstrip("0").zfill(10)
        data = self._get(EDGAR_SUBMISSIONS_URL.format(cik=cik_padded)).json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])

        def _date(values: list, i: int) -> Optional[datetime]:
            try:
                return datetime.strptime(str(values[i]), "%Y-%m-%d")
            except IndexError, ValueError:
                return None

        return [
            Filing(
                form=form,
                accession=str(accessions[i]).replace("-", ""),
                filing_date=_date(filing_dates, i),
                report_date=_date(report_dates, i),
            )
            for i, form in enumerate(forms)
            if form in (FORM_13F, FORM_13F_AMENDMENT) and i < len(accessions)
        ]

    def _period_holdings(
        self, cik_padded: str, period: list[Filing]
    ) -> tuple[list[Holding], Optional[Filing]]:
        """
        One quarter's holdings: the newest complete filing (13F-HR, or a
        RESTATEMENT amendment) plus the NEW HOLDINGS amendments filed after
        it. `period` is newest first. Returns the holdings and the complete
        filing, or ([], None) when the period has no complete filing.
        """
        parts: list[list[Holding]] = []
        for filing in period:
            info_url, primary_url = self._filing_documents(cik_padded, filing.accession)
            if info_url is None:
                logger.warning(f"No information table in filing {filing.accession}")
                continue
            if filing.form == FORM_13F:
                kind: Optional[str] = RESTATEMENT
            else:
                kind = self._amendment_type(primary_url) if primary_url else None
            if kind not in (RESTATEMENT, NEW_HOLDINGS):
                logger.warning(
                    f"Skipped amendment {filing.accession}: unknown amendment type {kind!r}"
                )
                continue
            parts.append(self._parse_information_table(info_url))
            if kind == RESTATEMENT:
                return aggregate_holdings([h for part in parts for h in part]), filing
        return [], None

    def _filing_documents(
        self, cik_padded: str, accession: str
    ) -> tuple[Optional[str], Optional[str]]:
        """URLs of a filing's information table and primary document, from its index."""
        base = f"{EDGAR_ARCHIVES_URL}/{cik_padded.lstrip('0')}/{accession}"
        try:
            index_data = self._get(f"{base}/index.json").json()
        except Exception as e:
            logger.debug(f"Failed to fetch filing index {accession}: {e}")
            return None, None

        names = [
            str(item.get("name", ""))
            for item in index_data.get("directory", {}).get("item", [])
            if str(item.get("name", "")).lower().endswith(".xml")
        ]
        primary = next((n for n in names if "primary" in n.lower()), None)
        info = next((n for n in names if "infotable" in n.lower()), None)
        # Some filers name the information table freely: any other XML file
        info = info or next((n for n in names if n != primary), None)
        return (
            f"{base}/{info}" if info else None,
            f"{base}/{primary}" if primary else None,
        )

    def _amendment_type(self, url: str) -> Optional[str]:
        """RESTATEMENT or NEW HOLDINGS, from an amendment's primary document."""
        try:
            root = ET.fromstring(self._get(url).content)
        except Exception as e:
            logger.warning(f"Could not read amendment {url}: {e}")
            return None
        element = root.find(".//{*}amendmentType")
        return element.text.strip().upper() if element is not None and element.text else None

    def _parse_information_table(self, url: str) -> list[Holding]:
        """Holdings in one 13F information table, before summing per CUSIP."""
        try:
            content = self._get(url).content
        except Exception as e:
            logger.error(f"Failed to fetch information table: {e}")
            return []
        return parse_information_table(content)

    # ==================== Serialization ====================

    def _serialize_portfolio(self, portfolio: TrackedPortfolio) -> dict:
        """Serialize a TrackedPortfolio for JSON caching."""
        return {
            "cache_version": CACHE_VERSION,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "name": portfolio.name,
            "source": portfolio.source,
            "cik": portfolio.cik,
            "filing_date": portfolio.filing_date.isoformat() if portfolio.filing_date else None,
            "period_of_report": (
                portfolio.period_of_report.isoformat() if portfolio.period_of_report else None
            ),
            "accessions": portfolio.accessions,
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

        def _datetime(value: Any) -> Optional[datetime]:
            try:
                return datetime.fromisoformat(value) if value else None
            except TypeError, ValueError:
                return None

        holdings = [
            Holding(
                ticker=h["ticker"],
                name=h["name"],
                shares=h.get("shares"),
                value=h.get("value"),
                sector=h.get("sector"),
                industry=h.get("industry"),
                weight=h.get("weight"),
                action=h.get("action"),
                date=_datetime(h.get("date")),
            )
            for h in data.get("holdings", [])
        ]
        return TrackedPortfolio(
            name=data["name"],
            source=data.get("source", "edgar_13f"),
            holdings=holdings,
            cik=data.get("cik"),
            filing_date=_datetime(data.get("filing_date")),
            period_of_report=_datetime(data.get("period_of_report")),
            accessions=list(data.get("accessions") or []),
        )


# ==================== Pure helpers ====================


def latest_periods(filings: list[Filing], count: int = 2) -> list[list[Filing]]:
    """
    The filings of the `count` latest report dates, newest period first, and
    within a period newest filing first. Filings without a report date are
    left out.
    """
    by_period: dict[datetime, list[Filing]] = {}
    for filing in filings:
        if filing.report_date is not None:
            by_period.setdefault(filing.report_date, []).append(filing)
    periods = sorted(by_period, reverse=True)[:count]
    return [
        sorted(
            by_period[p],
            key=lambda f: (f.filing_date or datetime.min, f.accession),
            reverse=True,
        )
        for p in periods
    ]


def parse_information_table(content: bytes) -> list[Holding]:
    """
    Long stock positions in a 13F information table, one per row (see
    `aggregate_holdings`). Option rows and principal-amount rows are skipped.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.error(f"Failed to parse information table XML: {e}")
        return []

    holdings = []
    skipped = 0
    for entry in root.iter():
        if str(entry.tag).rsplit("}", 1)[-1] != "infoTable":
            continue
        if _text(entry, "putCall") or (_text(entry, "shrsOrPrnAmt/sshPrnamtType") or "SH") != "SH":
            skipped += 1
            continue
        holding = _parse_entry(entry)
        if holding:
            holdings.append(holding)
    if skipped:
        logger.debug(f"Skipped {skipped} option or principal-amount rows")
    return holdings


def _text(element: ET.Element, path: str) -> Optional[str]:
    """Text at a slash-separated path of local names, in any namespace."""
    found = element.find("/".join(f"{{*}}{part}" for part in path.split("/")))
    if found is None:
        found = element.find(path)
    if found is not None and found.text and found.text.strip():
        return found.text.strip()
    return None


def _float(text: Optional[str]) -> Optional[float]:
    try:
        return float(text.replace(",", "")) if text else None
    except ValueError:
        return None


def _parse_entry(entry: ET.Element) -> Optional[Holding]:
    name = _text(entry, "nameOfIssuer")
    if not name:
        return None
    cusip = _text(entry, "cusip")
    # 13F filings use CUSIPs; HoldingEnricher maps them to tickers later
    return Holding(
        ticker=cusip or name.upper().replace(" ", ".")[:10],
        name=name,
        # Whole USD since January 2023 (thousands before); only recent filings are read
        value=_float(_text(entry, "value")),
        shares=_float(_text(entry, "shrsOrPrnAmt/sshPrnamt")),
    )


def _add(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return b if a is None else a if b is None else a + b


def aggregate_holdings(holdings: list[Holding]) -> list[Holding]:
    """
    One holding per identifier (CUSIP), shares and values summed. A filer
    lists a CUSIP once per manager or discretion type. Returns new objects;
    the input is not modified.
    """
    merged: dict[str, Holding] = {}
    for h in holdings:
        existing = merged.get(h.ticker)
        if existing is None:
            merged[h.ticker] = replace(h)
        else:
            existing.shares = _add(existing.shares, h.shares)
            existing.value = _add(existing.value, h.value)
    return list(merged.values())


def diff_holdings(
    current: list[Holding],
    previous: list[Holding],
    filing_date: Optional[datetime] = None,
) -> list[Holding]:
    """
    The current holdings (summed per identifier, as new objects) with
    `action` and `date` set, plus an "exit" placeholder (zero shares and
    value) for each previous holding no longer held.
    """
    prev_map = {h.ticker: h for h in aggregate_holdings(previous)}
    result = aggregate_holdings(current)
    for h in result:
        h.date = filing_date
        prev = prev_map.get(h.ticker)
        if prev is None:
            h.action = "new"
        elif h.shares and prev.shares:
            change = (h.shares - prev.shares) / prev.shares
            h.action = (
                "add"
                if change > ACTION_THRESHOLD
                else "trim"
                if change < -ACTION_THRESHOLD
                else "hold"
            )
        else:
            h.action = "hold"

    held = {h.ticker for h in result}
    result += [
        Holding(
            ticker=ticker,
            name=prev.name,
            shares=0,
            value=0,
            sector=prev.sector,
            industry=prev.industry,
            action="exit",
            date=filing_date,
        )
        for ticker, prev in prev_map.items()
        if ticker not in held
    ]
    return result


def set_weights(holdings: list[Holding]) -> None:
    """Each held position's share of the reported value, in percent."""
    total = sum(h.value or 0.0 for h in holdings if h.action != "exit")
    for h in holdings:
        h.weight = (h.value / total * 100) if total > 0 and h.value else None
