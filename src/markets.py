"""
Market / Exchange Helpers

Maps Yahoo Finance ticker suffixes to a local benchmark index so risk metrics
(beta, alpha, information ratio) compare a stock against its home market
rather than always against the S&P 500.
"""

from typing import Dict, Optional

from .config import get_config

# Yahoo suffix -> (benchmark symbol, display name)
DEFAULT_BENCHMARKS: Dict[str, tuple[str, str]] = {
    ".OL": ("OSEBX.OL", "Oslo Børs Benchmark"),
    ".ST": ("^OMX", "OMX Stockholm 30"),
    ".CO": ("^OMXC25", "OMX Copenhagen 25"),
    ".HE": ("^OMXH25", "OMX Helsinki 25"),
    ".L": ("^FTSE", "FTSE 100"),
    ".DE": ("^GDAXI", "DAX"),
    ".PA": ("^FCHI", "CAC 40"),
    ".AS": ("^AEX", "AEX"),
    ".BR": ("^BFX", "BEL 20"),
    ".MC": ("^IBEX", "IBEX 35"),
    ".MI": ("FTSEMIB.MI", "FTSE MIB"),
    ".SW": ("^SSMI", "SMI"),
    ".TO": ("^GSPTSE", "S&P/TSX Composite"),
    ".AX": ("^AXJO", "S&P/ASX 200"),
    ".HK": ("^HSI", "Hang Seng"),
    ".T": ("^N225", "Nikkei 225"),
}

_KNOWN_NAMES: Dict[str, str] = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq-100",
    "^IXIC": "Nasdaq Composite",
    "^DJI": "Dow Jones",
    **{symbol: name for symbol, name in DEFAULT_BENCHMARKS.values()},
}


def ticker_suffix(ticker: str) -> Optional[str]:
    """Return the exchange suffix of a Yahoo ticker (e.g. '.OL'), or None for US listings."""
    ticker = ticker.upper()
    if ticker.startswith("^") or "." not in ticker:
        return None
    return "." + ticker.rsplit(".", 1)[1]


def benchmark_for(ticker: str) -> str:
    """
    Pick the benchmark index for a ticker based on its exchange suffix.

    Resolution order: config.benchmark_by_suffix override, built-in map,
    then config.benchmark_ticker (default ^GSPC). Unsuffixed tickers are
    US listings (including ADRs such as EQNR) and use the default.
    """
    config = get_config()
    suffix = ticker_suffix(ticker)
    if suffix:
        overrides = {k.upper(): v for k, v in (config.benchmark_by_suffix or {}).items()}
        if suffix in overrides:
            return overrides[suffix]
        if suffix in DEFAULT_BENCHMARKS:
            return DEFAULT_BENCHMARKS[suffix][0]
    return config.benchmark_ticker


def benchmark_name(symbol: Optional[str]) -> str:
    """Human-readable benchmark name, falling back to the symbol itself."""
    if not symbol:
        return "benchmark"
    return _KNOWN_NAMES.get(symbol.upper(), symbol)
