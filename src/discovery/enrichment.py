"""
CUSIP-to-ticker resolution and sector enrichment.

13F filings report holdings by CUSIP (a 9-character identifier). CUSIPs are
mapped to tickers with OpenFIGI (Bloomberg's free identifier service,
https://www.openfigi.com/api), which gives each share class its own ticker.
Sectors and industries come from Yahoo through DataFetcher.

Caches, under `data/_discovery/enrichment/`:
- `cusip_tickers.json`: CUSIP -> ticker, hits only (also read by `quant vet`).
  The older `cusip_map.json` came from a fuzzy name search (both Alphabet
  classes were GOOG) and is no longer read.
- `cusip_misses.json`: CUSIP -> date OpenFIGI didn't know it; retried after
  MISS_TTL_DAYS. A network error caches nothing.
- `sector_map.json`: ticker -> sector/industry, hits only.
"""

import json
import logging
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..data_fetcher import DataFetcher
from ..paths import CUSIP_TICKERS
from ..utils.files import atomic_write_text
from .models import TrackedPortfolio

logger = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
# OpenFIGI's limits: 10 jobs per request and 25 requests a minute without a
# key; 100 jobs and 25 requests per 6 seconds with one
BATCH_SIZE = 10
BATCH_SIZE_WITH_KEY = 100
REQUEST_INTERVAL = 60 / 25
REQUEST_INTERVAL_WITH_KEY = 6 / 25
MISS_TTL_DAYS = 30
OPENFIGI_RETRY = Retry(
    total=3,
    backoff_factor=2.0,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),  # a mapping request is a pure lookup
    respect_retry_after_header=True,
)


def is_cusip(identifier: str) -> bool:
    """9 alphanumeric characters with at least one digit (tickers have none)."""
    return len(identifier) == 9 and identifier.isalnum() and any(c.isdigit() for c in identifier)


def yahoo_symbol(figi_ticker: str) -> str:
    """OpenFIGI writes share classes as BRK/B; Yahoo as BRK-B."""
    return figi_ticker.strip().upper().replace("/", "-").replace(" ", "-")


class HoldingEnricher:
    """
    Resolves CUSIP identifiers to ticker symbols and adds sector/industry.
    """

    def __init__(
        self,
        cache_dir: str = "data",
        fetcher: DataFetcher | None = None,
        api_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        from ..config import get_config

        self.cache_dir = Path(cache_dir) / "_discovery" / "enrichment"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cusip_cache_file = Path(cache_dir) / CUSIP_TICKERS
        self._miss_cache_file = self.cache_dir / "cusip_misses.json"
        self._sector_cache_file = self.cache_dir / "sector_map.json"
        self._cusip_map: dict[str, str] = self._load(self._cusip_cache_file)
        self._misses: dict[str, str] = self._load(self._miss_cache_file)
        self._sector_map: dict[str, dict] = {
            k: v
            for k, v in self._load(self._sector_cache_file).items()
            if isinstance(v, dict) and v.get("sector")
        }
        self.fetcher = fetcher or DataFetcher(cache_dir=cache_dir)
        self.api_key = api_key if api_key is not None else get_config().openfigi_api_key
        self._sleep = sleep
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(max_retries=OPENFIGI_RETRY))
        self._last_request = 0.0

    # ==================== Caches ====================

    @staticmethod
    def _load(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Ignoring unreadable cache {path}: {e}")
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _save(path: Path, data: dict) -> None:
        try:
            atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True))
        except OSError as e:
            logger.warning(f"Failed to save {path.name}: {e}")

    def _save_caches(self) -> None:
        self._save(self._cusip_cache_file, self._cusip_map)
        self._save(self._miss_cache_file, self._misses)
        self._save(self._sector_cache_file, self._sector_map)

    def _recent_miss(self, cusip: str, now: datetime) -> bool:
        try:
            when = datetime.fromisoformat(self._misses[cusip])
        except KeyError, ValueError:
            return False
        return now - when < timedelta(days=MISS_TTL_DAYS)

    # ==================== Enrichment ====================

    def enrich_portfolio(self, portfolio: TrackedPortfolio) -> TrackedPortfolio:
        """Resolve and enrich every holding of one portfolio (in place)."""
        self.enrich_tickers_in_portfolios([portfolio], portfolio.tickers)
        return portfolio

    def enrich_tickers_in_portfolios(
        self, portfolios: list[TrackedPortfolio], tickers: Iterable[str]
    ) -> None:
        """
        Give the holdings whose identifier is in `tickers` their real ticker
        (CUSIPs resolved through OpenFIGI) and sector/industry (from Yahoo).
        Unresolved CUSIPs are left as they are. Updates `portfolios` in place.
        """
        identifiers = set(tickers)
        resolved = self.resolve_cusips(sorted(i for i in identifiers if is_cusip(i)))
        mapping = {i: resolved.get(i, i) for i in identifiers}

        real_tickers = {t for t in mapping.values() if not is_cusip(t)}
        to_fetch = sorted(t for t in real_tickers if t not in self._sector_map)
        logger.info(
            f"Enriching {len(identifiers)} identifiers -> {len(real_tickers)} tickers "
            f"({len(to_fetch)} need a sector lookup)"
        )
        for ticker in to_fetch:
            self._lookup_sector(ticker)

        for portfolio in portfolios:
            for holding in portfolio.holdings:
                if holding.ticker not in identifiers:
                    continue
                ticker = mapping[holding.ticker]
                holding.ticker = ticker
                sector = self._sector_map.get(ticker)
                if sector:
                    holding.sector = sector.get("sector")
                    holding.industry = sector.get("industry")
        self._save_caches()

    def _lookup_sector(self, ticker: str) -> None:
        info = self.fetcher.get_ticker_info(ticker)
        sector = info.get("sector")
        if sector and sector != "N/A":
            industry = info.get("industry")
            self._sector_map[ticker] = {
                "sector": sector,
                "industry": industry if industry != "N/A" else None,
            }

    # ==================== CUSIP -> ticker ====================

    def resolve_cusips(self, cusips: list[str]) -> dict[str, str]:
        """
        CUSIP -> ticker for the CUSIPs that can be resolved: from the cache,
        else from OpenFIGI. A miss is asked again in a second form (see
        `_fallback_job`). A CUSIP neither form finds is remembered for
        MISS_TTL_DAYS; one that failed on a network error is tried next run.
        """
        now = datetime.now()
        result = {c: self._cusip_map[c] for c in cusips if c in self._cusip_map}
        pending = [c for c in cusips if c not in result and not self._recent_miss(c, now)]
        misses = self._lookup(pending, _primary_job, result, us_only=False)
        if misses:
            for cusip in self._lookup(misses, _fallback_job, result, us_only=True) or []:
                self._misses[cusip] = now.date().isoformat()
        return result

    def _lookup(
        self,
        cusips: list[str],
        job: Callable[[str], dict],
        result: dict[str, str],
        us_only: bool,
    ) -> list[str] | None:
        """
        Ask OpenFIGI in batches; hits go into `result` and the cache. Returns
        the CUSIPs OpenFIGI doesn't know, or None when a request failed (the
        rest are left for the next run).
        """
        misses: list[str] = []
        size = BATCH_SIZE_WITH_KEY if self.api_key else BATCH_SIZE
        for start in range(0, len(cusips), size):
            batch = cusips[start : start + size]
            try:
                answers = self._openfigi([job(c) for c in batch])
            except (requests.RequestException, ValueError) as e:
                logger.warning(
                    f"OpenFIGI lookup failed ({e}); {len(cusips) - start} CUSIPs left "
                    "unresolved for now"
                )
                return None
            for cusip, answer in zip(batch, answers, strict=False):
                ticker = _ticker_from(answer, us_only=us_only)
                if ticker:
                    self._cusip_map[cusip] = ticker
                    self._misses.pop(cusip, None)
                    result[cusip] = ticker
                elif isinstance(answer, dict) and ("warning" in answer or "data" in answer):
                    misses.append(cusip)
                else:
                    # An error for one job (e.g. a malformed request); tried again next run
                    logger.warning(f"OpenFIGI could not look up {cusip}: {answer}")
        return misses

    def _openfigi(self, jobs: list[dict]) -> list[Any]:
        """One mapping request; one answer per job, in order."""
        interval = REQUEST_INTERVAL_WITH_KEY if self.api_key else REQUEST_INTERVAL
        wait = self._last_request + interval - time.monotonic()
        if self._last_request and wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        response = self._session.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        response.raise_for_status()
        answers = response.json()
        if not isinstance(answers, list) or len(answers) != len(jobs):
            raise ValueError("unexpected OpenFIGI response")
        return answers


def _primary_job(cusip: str) -> dict:
    return {"idType": "ID_CUSIP", "idValue": cusip, "exchCode": "US"}


def _fallback_job(cusip: str) -> dict:
    """
    The second try for a miss. A CUSIP starting with a letter is a CINS, the
    form for issuers outside the US and Canada (ASML N07059210, Wix
    M98068105), which OpenFIGI files under ID_CINS. Others are asked
    without the US-composite filter (seen live: Roku had no answer with
    it). `_ticker_from` then keeps US listings only.
    """
    if cusip[:1].isalpha():
        return {"idType": "ID_CINS", "idValue": cusip}
    return {"idType": "ID_CUSIP", "idValue": cusip}


def _is_us_listing(exch_code: Any) -> bool:
    """OpenFIGI's US composite ("US") or a US exchange (UN NYSE, UW/UQ/UR Nasdaq, ...)."""
    code = str(exch_code or "")
    return code == "US" or (len(code) == 2 and code.startswith("U"))


def _ticker_from(answer: Any, us_only: bool = False) -> str | None:
    """
    The ticker in one OpenFIGI answer ({"data": [...]}), preferring equity
    and the US composite. With `us_only`, listings outside the US are ignored
    (a foreign ticker would need a Yahoo suffix).
    """
    if not isinstance(answer, dict):
        return None
    data = [
        d
        for d in answer.get("data") or []
        if isinstance(d, dict)
        and d.get("ticker")
        and (not us_only or _is_us_listing(d.get("exchCode")))
    ]
    data.sort(key=lambda d: (d.get("marketSector") != "Equity", d.get("exchCode") != "US"))
    return yahoo_symbol(str(data[0]["ticker"])) if data else None
