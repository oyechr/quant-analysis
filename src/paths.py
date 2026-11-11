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
