"""
Ticker Universes

Resolves what to screen: built-in index lists (fetched from Nasdaq's
constituent API or Wikipedia, then cached), the latest `quant discover`
consensus picks, a ticker file, or literal tickers.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd
import requests

from ..config import get_config

logger = logging.getLogger(__name__)

_WIKIPEDIA_HEADERS = {"User-Agent": "quant-analysis/0.1 (personal research tool)"}
# api.nasdaq.com rejects requests without browser-like headers
_NASDAQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
NASDAQ_LIST_URL = "https://api.nasdaq.com/api/quote/list-type/{list_type}"
_US_SHARE_CLASS = re.compile(r"^[A-Z]{1,5}\.[A-Z]$")  # BRK.B -> BRK-B on Yahoo
_CUSIP = re.compile(r"^[0-9A-Z]{9}$")


@dataclass(frozen=True)
class IndexSource:
    """
    Where an index's constituents come from.

    Sources are tried in order: Nasdaq's constituent API (when `nasdaq_list`
    is set), then the Wikipedia table at `url`.
    """

    name: str
    description: str
    url: str  # Wikipedia page with a constituents table
    column_candidates: tuple[str, ...]
    yahoo_suffix: str = ""  # appended to each symbol, e.g. ".OL"
    us_listing: bool = True  # convert share-class dots to Yahoo dashes
    min_expected: int = 10  # sanity check against grabbing the wrong table
    nasdaq_list: Optional[str] = None  # list-type for api.nasdaq.com, e.g. "nasdaq100"


BUILTIN_INDEXES: Dict[str, IndexSource] = {
    "sp500": IndexSource(
        name="sp500",
        description="S&P 500 constituents",
        url="https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        column_candidates=("Symbol", "Ticker"),
        min_expected=400,
    ),
    "nasdaq100": IndexSource(
        name="nasdaq100",
        description="Nasdaq-100 constituents",
        url="https://en.wikipedia.org/wiki/Nasdaq-100",
        column_candidates=("Ticker", "Symbol"),
        min_expected=90,
        nasdaq_list="nasdaq100",
    ),
    "sp100": IndexSource(
        name="sp100",
        description="S&P 100 constituents (fast US large-cap screen)",
        url="https://en.wikipedia.org/wiki/S%26P_100",
        column_candidates=("Symbol", "Ticker"),
        min_expected=90,
    ),
    "obx": IndexSource(
        name="obx",
        description="OBX (Oslo Børs 25 most traded) constituents",
        url="https://en.wikipedia.org/wiki/OBX_Index",
        column_candidates=("Ticker", "Symbol", "Ticker symbol"),
        yahoo_suffix=".OL",
        us_listing=False,
        min_expected=15,
    ),
}

DISCOVER_UNIVERSE = "discover"


@dataclass
class Universe:
    """Resolved list of tickers plus where they came from."""

    tickers: List[str]
    sources: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return "+".join(self.sources) if self.sources else "custom"


def list_universes() -> Dict[str, str]:
    """Built-in universe names and descriptions (for --help / listings)."""
    names = {name: src.description for name, src in BUILTIN_INDEXES.items()}
    names[DISCOVER_UNIVERSE] = "Consensus picks from the latest `quant discover` run"
    return names


def resolve_universe(
    specs: List[str],
    data_dir: str = "data",
    use_cache: bool = True,
    fetch_text: Optional[Callable[[str], str]] = None,
) -> Universe:
    """
    Resolve universe specs into a de-duplicated ticker list (order preserved).

    Each spec is one of:
      - a built-in index name (sp500, sp100, nasdaq100, obx)
      - "discover": overlap tickers from data/_discovery/discovery_result.json
      - a path to a ticker file (one per line or comma-separated; '#' comments;
        CSV with a ticker/symbol column also works)
      - otherwise, a literal ticker symbol

    Raises:
        ValueError: If a built-in or discover universe can't be loaded
    """
    tickers: List[str] = []
    sources: List[str] = []
    literals: List[str] = []

    for spec in specs:
        key = spec.strip().lower()
        if key in BUILTIN_INDEXES:
            tickers.extend(
                load_index(BUILTIN_INDEXES[key], data_dir, use_cache, fetch_text=fetch_text)
            )
            sources.append(key)
        elif key == DISCOVER_UNIVERSE:
            tickers.extend(load_discover_tickers(data_dir))
            sources.append(key)
        elif Path(spec).is_file():
            tickers.extend(load_ticker_file(Path(spec)))
            sources.append(Path(spec).stem)
        else:
            literals.append(spec.strip().upper())

    tickers.extend(literals)
    if literals:
        sources.append("tickers")
    return Universe(tickers=list(dict.fromkeys(t for t in tickers if t)), sources=sources)


def load_index(
    source: IndexSource,
    data_dir: str = "data",
    use_cache: bool = True,
    fetch_text: Optional[Callable[[str], str]] = None,
) -> List[str]:
    """
    Load index constituents, using a cached copy when younger than the
    'universe' TTL. Tries each configured source in turn, and falls back to an
    expired cache if all of them fail.

    Args:
        fetch_text: Override for HTTP GET (url -> body); used by tests.
    """
    cache_file = Path(data_dir) / "_universes" / f"{source.name}.json"
    cached = _read_universe_cache(cache_file)
    ttl_hours = (get_config().cache_ttl_hours or {}).get("universe", 0)

    if use_cache and cached and _cache_age_hours(cached) < (ttl_hours or float("inf")):
        return list(cached["tickers"])

    attempts: List[tuple[str, Callable[[str, IndexSource], List[str]]]] = []
    if source.nasdaq_list:
        attempts.append((NASDAQ_LIST_URL.format(list_type=source.nasdaq_list), parse_nasdaq_list))
    attempts.append((source.url, parse_constituents))

    failures: List[str] = []
    for url, parse in attempts:
        try:
            tickers = parse((fetch_text or _http_get)(url), source)
        except Exception as e:
            logger.info(f"{source.name}: {url} failed ({e})")
            failures.append(f"{url}: {e}")
            continue

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(
                {"source": url, "fetched_at": datetime.now().isoformat(), "tickers": tickers},
                indent=2,
            ),
            encoding="utf-8",
        )
        return tickers

    if cached:
        logger.warning(f"Could not refresh {source.name}; using cached list")
        return list(cached["tickers"])
    raise ValueError(
        f"Could not load the {source.name} universe:\n  "
        + "\n  ".join(failures)
        + "\nPass a ticker file instead, e.g. `quant screen my_tickers.txt`."
    )


def parse_nasdaq_list(text: str, source: IndexSource) -> List[str]:
    """
    Parse api.nasdaq.com list-type JSON.

    The payload nests rows under data.data.rows (layout has shifted over time),
    so this takes the largest list of objects that have a 'symbol' field.
    """
    rows = max(_symbol_rows(json.loads(text)), key=len, default=[])
    symbols = [_to_yahoo(str(row["symbol"]).replace("/", "."), source) for row in rows]
    tickers = list(dict.fromkeys(s for s in symbols if s))
    if len(tickers) < source.min_expected:
        raise ValueError(f"expected at least {source.min_expected} symbols, got {len(tickers)}")
    return tickers


def _symbol_rows(node: object) -> List[List[dict]]:
    """All lists of dicts with a 'symbol' key anywhere in a JSON document."""
    found: List[List[dict]] = []
    if isinstance(node, list):
        if node and all(isinstance(x, dict) and "symbol" in x for x in node):
            found.append(node)
        for item in node:
            found.extend(_symbol_rows(item))
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(_symbol_rows(value))
    return found


def parse_constituents(html: str, source: IndexSource) -> List[str]:
    """
    Read constituents from a Wikipedia page; normalize to Yahoo symbols.

    Uses the first table with a ticker column and enough rows. Some pages split
    the list across several tables (e.g. by sector), so if no single table is
    big enough, all tables with a ticker column are combined.
    """
    tables = pd.read_html(StringIO(html))
    wanted = [c.lower() for c in source.column_candidates]
    seen: List[str] = []
    ticker_columns: List[pd.Series] = []
    for table in tables:
        columns = {_clean_header(c): c for c in table.columns}
        column = next((columns[w] for w in wanted if w in columns), None)
        if len(table) >= source.min_expected:
            seen.append(f"{len(table)} rows: {', '.join(list(columns)[:8])}")
        if column is None:
            continue
        values = table[column]
        if isinstance(values, pd.DataFrame):  # duplicated header across levels
            values = values.iloc[:, 0]
        if len(table) >= source.min_expected:
            return _normalize_symbols(values, source)
        ticker_columns.append(values)

    if ticker_columns and sum(len(v) for v in ticker_columns) >= source.min_expected:
        combined = _normalize_symbols(pd.concat(ticker_columns, ignore_index=True), source)
        if len(combined) >= source.min_expected:
            return combined

    raise ValueError(
        f"No table with a {'/'.join(source.column_candidates)} column "
        f"and at least {source.min_expected} rows. "
        f"Tables found: {' | '.join(seen) or 'none large enough'}"
    )


def _normalize_symbols(values: pd.Series, source: IndexSource) -> List[str]:
    symbols = [_to_yahoo(str(s), source) for s in values.dropna()]
    return list(dict.fromkeys(s for s in symbols if s))


def _clean_header(column: object) -> str:
    """
    Normalize a table header for matching.

    Handles two-row headers (tuples from pandas), footnote markers such as
    "Symbol[a]" or "Symbol[12]", and stray whitespace.
    """
    if isinstance(column, tuple):
        column = next((c for c in reversed(column) if not str(c).startswith("Unnamed")), column[-1])
    return re.sub(r"\[[^\]]*\]", "", str(column)).strip().lower()


def load_discover_tickers(data_dir: str = "data") -> List[str]:
    """Consensus tickers from the most recent `quant discover` run, strongest first."""
    path = Path(data_dir) / "_discovery" / "discovery_result.json"
    if not path.exists():
        raise ValueError(f"No discovery results at {path}. Run `quant discover` first.")
    result = json.loads(path.read_text(encoding="utf-8"))
    tickers: List[str] = []
    for signal in result.get("overlap_signals", []):
        ticker = str(signal.get("ticker") or "").upper()
        if not ticker or (_CUSIP.match(ticker) and any(ch.isdigit() for ch in ticker)):
            continue  # unresolved CUSIP, not a tradable symbol
        tickers.append(_US_SHARE_CLASS.sub(lambda m: m.group(0).replace(".", "-"), ticker))
    return list(dict.fromkeys(tickers))


def load_ticker_file(path: Path) -> List[str]:
    """
    Read tickers from a text or CSV file.

    Text: one or more tickers per line separated by commas/whitespace; '#' starts a comment.
    CSV: if the header has a 'ticker' or 'symbol' column, that column is used.
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header = [h.strip().lower() for h in lines[0].split(",")] if lines else []
    for name in ("ticker", "symbol"):
        if name in header:
            column = header.index(name)
            rows = [line.split(",") for line in lines[1:] if line.strip()]
            return [row[column].strip().upper() for row in rows if len(row) > column]

    tickers: List[str] = []
    for line in lines:
        line = line.split("#", 1)[0]
        tickers.extend(t.strip().upper() for t in re.split(r"[,\s]+", line) if t.strip())
    return tickers


def _to_yahoo(symbol: str, source: IndexSource) -> str:
    symbol = symbol.strip().upper()
    if not symbol or symbol == "NAN":
        return ""
    symbol = symbol.split(":")[-1].strip()  # "NYSE: MMM" / "OSE: EQNR" -> bare symbol
    if source.yahoo_suffix:
        return symbol if symbol.endswith(source.yahoo_suffix) else symbol + source.yahoo_suffix
    if source.us_listing and _US_SHARE_CLASS.match(symbol):
        return symbol.replace(".", "-")
    return symbol


def _http_get(url: str) -> str:
    headers = _NASDAQ_HEADERS if "nasdaq.com" in url else _WIKIPEDIA_HEADERS
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def _read_universe_cache(cache_file: Path) -> Optional[dict]:
    if not cache_file.exists():
        return None
    try:
        data: dict = json.loads(cache_file.read_text(encoding="utf-8"))
        return data
    except json.JSONDecodeError, OSError:
        return None


def _cache_age_hours(cached: dict) -> float:
    try:
        fetched = datetime.fromisoformat(cached["fetched_at"])
    except KeyError, ValueError:
        return float("inf")
    return (datetime.now() - fetched).total_seconds() / 3600
