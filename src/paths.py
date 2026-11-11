"""
Default locations of the data folder and the personal files

All relative to the working directory (the repo root). The personal files
are gitignored. Commands take these as option defaults; library code takes
the path as an argument.
"""

DATA_DIR = "data"
WATCHLIST = "watchlist.toml"
PORTFOLIO = "portfolio/portfolio.csv"
TICKER_MAP = "portfolio/tickers.csv"
TARGETS = "portfolio/targets.toml"
JOURNAL = "portfolio/journal.toml"

# CUSIP -> ticker from OpenFIGI, written by `discover`, read by `vet`. Under
# DATA_DIR. (The older cusip_map.json came from a name search and is ignored.)
CUSIP_TICKERS = "_discovery/enrichment/cusip_tickers.json"
