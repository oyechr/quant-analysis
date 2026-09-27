"""
Nordnet Holdings Import

Reads Nordnet's holdings export ("aksjelister_konto-<account>_<date>.csv":
UTF-16, tab-separated, decimal commas, Norwegian headers) and combines one or
more accounts into the portfolio file `quant` uses:

    ticker,name,account,shares,cost_basis,currency

The export has instrument names but no tickers or ISINs, so names are mapped
to Yahoo tickers with a small CSV (`name,ticker`) kept next to the portfolio.
Unmapped names keep an empty ticker and are reported, so the map can be
filled in and the import rerun.

Real holdings belong in the gitignored `portfolio/` folder.
"""

import csv
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

PORTFOLIO_COLUMNS = ["ticker", "name", "account", "shares", "cost_basis", "currency"]

# Nordnet export header -> portfolio column (only the columns we keep)
_HEADERS = {
    "navn": "name",
    "valuta": "currency",
    "antall": "shares",
    "gav": "cost_basis",  # average purchase price per share, in the instrument currency
}

_ACCOUNT_IN_FILENAME = re.compile(r"konto-(\d+)", re.IGNORECASE)


def read_nordnet_holdings(path: Path, account: Optional[str] = None) -> pd.DataFrame:
    """
    One Nordnet holdings export as a frame with name, account, shares,
    cost_basis and currency.

    Args:
        path: The exported CSV
        account: Account label; defaults to the account number in the file name
    """
    path = Path(path)
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    frame = pd.read_csv(path, sep="\t", encoding=encoding, dtype=str)
    frame.columns = [str(c).strip().lower() for c in frame.columns]

    missing = [h for h in _HEADERS if h not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: not a Nordnet holdings export (missing {missing})")

    out = frame[list(_HEADERS)].rename(columns=_HEADERS)
    out["name"] = out["name"].str.strip()
    out["currency"] = out["currency"].str.strip()
    for column in ("shares", "cost_basis"):
        out[column] = out[column].map(_nordnet_number)
    if account is None:
        match = _ACCOUNT_IN_FILENAME.search(path.name)
        account = match.group(1) if match else path.stem
    out["account"] = account
    return out[out["name"].astype(bool) & (out["shares"] > 0)].reset_index(drop=True)


def load_ticker_map(path: Path) -> Dict[str, str]:
    """Instrument name -> Yahoo ticker, from a `name,ticker` CSV (missing file: empty)."""
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {
            row["name"].strip(): row["ticker"].strip().upper()
            for row in csv.DictReader(f)
            if row.get("name") and row.get("ticker")
        }


def combine_holdings(
    exports: Iterable[Tuple[Path, Optional[str]]], ticker_map: Dict[str, str]
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Holdings from several exports in the portfolio format, one row per
    account and instrument, plus the names that have no ticker yet.
    """
    frames = [read_nordnet_holdings(path, account) for path, account in exports]
    holdings = pd.concat(frames, ignore_index=True)
    holdings["ticker"] = holdings["name"].map(ticker_map).fillna("")
    unmapped = sorted(holdings.loc[holdings["ticker"] == "", "name"].unique())
    holdings = holdings.sort_values(["account", "ticker", "name"]).reset_index(drop=True)
    return holdings[PORTFOLIO_COLUMNS], unmapped


def write_portfolio(holdings: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    holdings[PORTFOLIO_COLUMNS].to_csv(path, index=False, encoding="utf-8")


def _nordnet_number(value: object) -> float:
    """'1 234,56' / '1 234,56' -> 1234.56; blanks -> NaN."""
    text = str(value or "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return float("nan")
