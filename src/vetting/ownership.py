"""
13F Fund Activity

Which tracked funds (see `quant discover`) hold a ticker, and what they did
in their latest 13F filing: new position, add, trim, hold, or exit.

Reads only the local cache written by `quant discover`:
`data/_discovery/edgar_13f/<CIK>.json` (holdings keyed by CUSIP) and
`data/_discovery/enrichment/cusip_map.json` (CUSIP -> ticker). Holdings whose
CUSIP isn't mapped are matched on issuer name instead, which also catches
US-listed ADRs of foreign tickers (EQNR.OL -> EQUINOR ASA).
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Most significant first, for picking one action when a fund holds several share classes
_ACTION_PRIORITY = {"new": 0, "exit": 1, "add": 2, "trim": 3, "hold": 4}

_NAME_NOISE = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|SA|S A|AG|NV|N V|ASA|AB|"
    r"SE|HOLDINGS?|GROUP|THE|CL(ASS)? [A-C]|COM|NEW|ADR|SPONSORED|SHS|ORD)\b"
)


@dataclass
class FundPosition:
    fund: str
    action: str
    shares: Optional[float]
    value: Optional[float]
    filing_date: Optional[str]
    period: Optional[str]
    matched_on: str  # "ticker" or "name"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundActivity:
    ticker: str
    positions: List[FundPosition] = field(default_factory=list)
    funds_checked: int = 0
    cache_found: bool = False

    @property
    def hint(self) -> Optional[str]:
        if not self.cache_found:
            return "No 13F cache found. Run `quant discover` to fetch tracked funds' filings."
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "funds_checked": self.funds_checked,
            "cache_found": self.cache_found,
            "positions": [p.to_dict() for p in self.positions],
        }


def fund_activity(ticker: str, company_name: Optional[str], data_dir: str = "data") -> FundActivity:
    """Look up the ticker in every cached 13F portfolio."""
    ticker = ticker.upper()
    result = FundActivity(ticker=ticker)
    cache_dir = Path(data_dir) / "_discovery" / "edgar_13f"
    files = sorted(cache_dir.glob("*.json")) if cache_dir.exists() else []
    if not files:
        return result
    result.cache_found = True

    cusip_map = _load_json(Path(data_dir) / "_discovery" / "enrichment" / "cusip_map.json") or {}
    symbols = _ticker_aliases(ticker)
    target_name = normalize_issuer(company_name) if company_name else ""

    for path in files:
        portfolio = _load_json(path)
        if not isinstance(portfolio, dict):
            continue
        result.funds_checked += 1
        position = _position_in(portfolio, symbols, target_name, cusip_map)
        if position:
            result.positions.append(position)

    result.positions.sort(key=lambda p: (_ACTION_PRIORITY.get(p.action, 9), -(p.value or 0)))
    return result


def normalize_issuer(name: str) -> str:
    """'Alphabet Inc. Class A' and 'ALPHABET INC CL A' both -> 'ALPHABET'."""
    text = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper())
    text = _NAME_NOISE.sub(" ", text)
    return " ".join(text.split())


def _position_in(
    portfolio: Dict[str, Any],
    symbols: set[str],
    target_name: str,
    cusip_map: Dict[str, str],
) -> Optional[FundPosition]:
    rows = []
    ticker_match = False
    for holding in portfolio.get("holdings") or []:
        identifier = str(holding.get("ticker") or "").upper()
        resolved = str(cusip_map.get(identifier, identifier)).upper()
        if resolved in symbols:
            rows.append(holding)
            ticker_match = True
        elif target_name and normalize_issuer(holding.get("name") or "") == target_name:
            rows.append(holding)
    if not rows:
        return None

    action = min(
        (str(r.get("action") or "hold") for r in rows),
        key=lambda a: _ACTION_PRIORITY.get(a, 9),
    )
    shares = sum(r.get("shares") or 0 for r in rows) or None
    value = sum(r.get("value") or 0 for r in rows) or None
    return FundPosition(
        fund=portfolio.get("name") or portfolio.get("cik") or "unknown",
        action=action,
        shares=shares,
        value=value,
        filing_date=_date_only(portfolio.get("filing_date")),
        period=_date_only(portfolio.get("period_of_report")),
        matched_on="ticker" if ticker_match else "name",
    )


def _ticker_aliases(ticker: str) -> set[str]:
    """
    Symbols a 13F holding might carry for this ticker: BRK-B -> {BRK-B, BRK.B}.

    Foreign listings are not reduced to their base symbol (DNB.OL is not DNB,
    Dun & Bradstreet); their US ADRs are found by issuer name instead.
    """
    return {ticker, ticker.replace("-", ".")}


def _date_only(value: Any) -> Optional[str]:
    return str(value)[:10] if value else None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(f"Could not read {path}: {e}")
        return None
