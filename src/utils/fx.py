"""
Currency Conversion for Financial Statements

Yahoo reports statements in the company's reporting currency, which can
differ from the currency the shares trade in (EQNR.OL: statements in USD,
price in NOK; many .L listings: statements in GBP, price in pence). Mixing the
two makes DCF values, FCF yield and market-value ratios wrong by the exchange
rate.

Statements are converted into the listing currency with one (latest) rate.
Scaling every period by the same constant leaves growth rates, margins and
other ratios unchanged; only the levels move.
"""

import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

# Listing currencies quoted in minor units: code -> (major currency, units per major)
MINOR_UNITS: Dict[str, Tuple[str, float]] = {
    "GBp": ("GBP", 100.0),
    "GBX": ("GBP", 100.0),
    "ZAc": ("ZAR", 100.0),
    "ZAC": ("ZAR", 100.0),
    "ILA": ("ILS", 100.0),
}

# Statement lines that are counts or rates, not money
_NON_MONETARY = re.compile(r"(Shares( Number)?$|^Share Issued$|^Tax Rate)", re.IGNORECASE)


def major_currency(code: str) -> Tuple[str, float]:
    """'GBp' -> ('GBP', 100.0); 'USD' -> ('USD', 1.0)."""
    if code in MINOR_UNITS:
        return MINOR_UNITS[code]
    return code.upper(), 1.0


def fx_symbol(from_currency: str, to_currency: str) -> str:
    """Yahoo symbol for the rate converting one unit of `from` into `to` (USDNOK=X)."""
    return f"{from_currency.upper()}{to_currency.upper()}=X"


def needs_conversion(statement_currency: Optional[str], listing_currency: Optional[str]) -> bool:
    if not statement_currency or not listing_currency:
        return False
    return statement_currency != listing_currency


def conversion_rate(
    statement_currency: str,
    listing_currency: str,
    fx_lookup: Callable[[str], Optional[float]],
) -> Optional[Tuple[float, Optional[str]]]:
    """
    Multiplier turning statement amounts into listing-currency amounts.

    Returns (rate, fx symbol used or None), or None if the FX rate is unavailable.
    """
    statement_major, statement_units = major_currency(statement_currency)
    listing_major, listing_units = major_currency(listing_currency)
    symbol = None
    rate = 1.0
    if statement_major != listing_major:
        symbol = fx_symbol(statement_major, listing_major)
        quoted = fx_lookup(symbol)
        if quoted is None or not math.isfinite(quoted) or quoted <= 0:
            return None
        rate = quoted
    return rate * listing_units / statement_units, symbol


def usd_per_unit(currency: str, fx_lookup: Callable[[str], Optional[float]]) -> Optional[float]:
    """
    USD value of one unit of `currency` (GBp -> GBPUSD / 100), or None if unknown.

    Tries the inverse of USDNOK=X first (usually already cached from
    statement conversion), then the direct pair NOKUSD=X.
    """
    major, units = major_currency(currency)
    if major == "USD":
        return 1.0 / units
    inverse = fx_lookup(fx_symbol("USD", major))
    if inverse is not None and math.isfinite(inverse) and inverse > 0:
        return 1.0 / inverse / units
    quoted = fx_lookup(fx_symbol(major, "USD"))
    if quoted is not None and math.isfinite(quoted) and quoted > 0:
        return quoted / units
    return None


def adjust_info_ratios(
    info: Dict[str, Any], rate: float, book_equity: Optional[float] = None
) -> Dict[str, Any]:
    """
    Fix Yahoo's statement-based ratios for a ticker whose statements are in
    another currency than its price.

    Yahoo computes these from the raw numbers without converting: for EQNR.OL,
    P/S is the NOK market cap over USD revenue, and enterprise value is the NOK
    market cap plus USD net debt. `rate` converts statement currency into the
    listing currency.

    Yahoo's P/B is sometimes right (EQNR.OL) and sometimes price over a
    statement-currency book value (VAR.OL: 59.7 instead of ~6), with no field
    telling which, so it's only replaced when `book_equity` (listing currency,
    from converted statements) is given. P/E is left alone. Yahoo's
    `freeCashflow` is left alone too, since its currency isn't consistent.

    The keys that were corrected are listed in `converted_ratios`; peer
    comparisons skip the other statement-based ratios of such tickers.
    Returns a copy; the original (cached) info is not modified.
    """
    out = dict(info)
    converted: List[str] = []
    price_to_sales = _num(info.get("price_to_sales"))
    if price_to_sales is not None:
        out["price_to_sales"] = price_to_sales / rate
        converted.append("price_to_sales")

    market_cap = _num(info.get("market_cap"))
    enterprise_value = _num(info.get("enterprise_value"))
    ev_to_ebitda = _num(info.get("ev_to_ebitda"))
    if market_cap and enterprise_value and ev_to_ebitda:
        ebitda = enterprise_value / ev_to_ebitda  # statement currency
        net_debt = enterprise_value - market_cap  # statement currency
        corrected_ev = market_cap + net_debt * rate
        out["enterprise_value"] = corrected_ev
        out["ev_to_ebitda"] = corrected_ev / (ebitda * rate)
        converted.append("ev_to_ebitda")

    if market_cap and book_equity and book_equity > 0:
        out["price_to_book"] = market_cap / book_equity
        converted.append("price_to_book")

    out["converted_ratios"] = converted
    return out


def normalize_info(
    info: Dict[str, Any], fx_lookup: Callable[[str], Optional[float]]
) -> Dict[str, Any]:
    """
    `info` with its statement-based ratios in the listing currency, where
    Yahoo mixed currencies and an FX rate is available (see adjust_info_ratios).

    The pipeline does the same for the analyzed ticker, using its converted
    statements for P/B as well.
    """
    statements, listing = info.get("financial_currency"), info.get("currency")
    if not needs_conversion(statements, listing):
        return info
    result = conversion_rate(str(statements), str(listing), fx_lookup)
    return adjust_info_ratios(info, result[0]) if result else info


def _num(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return result if math.isfinite(result) else None


def convert_statements(
    fundamentals: Dict[str, pd.DataFrame], rate: float
) -> Dict[str, pd.DataFrame]:
    """Copies of the statement frames with every monetary line multiplied by `rate`."""
    converted: Dict[str, pd.DataFrame] = {}
    for name, frame in fundamentals.items():
        if frame is None or frame.empty:
            converted[name] = frame
            continue
        monetary = [not _NON_MONETARY.search(str(row)) for row in frame.index]
        out = frame.apply(pd.to_numeric, errors="coerce")
        out.loc[monetary] = out.loc[monetary] * rate
        converted[name] = out
    return converted
