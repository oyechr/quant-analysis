"""
Data Fetcher Module
Handles fetching historical market data from Yahoo Finance
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import yfinance as yf

from .config import get_config
from .utils.serialization import dataframe_to_json_dict, dataframe_to_records, series_to_dataframe

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetches and caches financial market data"""

    def __init__(self, cache_dir: str = "data"):
        """
        Initialize DataFetcher

        Args:
            cache_dir: Directory to store cached data files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.config = get_config()

    def validate_ticker(self, ticker: str) -> bool:
        """
        Validate ticker symbol exists and is accessible

        Args:
            ticker: Stock ticker symbol

        Returns:
            True if ticker is valid, False otherwise
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            # Valid tickers return a dict with at least some data
            # Empty or error responses will have very few fields
            return len(info) > 5 and (
                info.get("symbol") is not None or info.get("longName") is not None
            )
        except Exception as e:
            logger.debug(f"Ticker validation failed for {ticker}: {e}")
            return False

    def _validate_params(
        self, period: Optional[str], interval: str, start: Optional[str], end: Optional[str]
    ):
        """
        Validate fetch parameters

        Args:
            period: Period string
            interval: Interval string
            start: Start date string
            end: End date string

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate period
        if period and not self.config.validate_period(period):
            valid_options = sorted(self.config.valid_periods) if self.config.valid_periods else []
            raise ValueError(f"Invalid period '{period}'. " f"Valid options: {valid_options}")

        # Validate interval
        if not self.config.validate_interval(interval):
            valid_options = (
                sorted(self.config.valid_intervals) if self.config.valid_intervals else []
            )
            raise ValueError(f"Invalid interval '{interval}'. " f"Valid options: {valid_options}")

        # Validate date range if provided
        if start and end:
            try:
                start_date = datetime.strptime(start, "%Y-%m-%d")
                end_date = datetime.strptime(end, "%Y-%m-%d")

                if start_date >= end_date:
                    raise ValueError(f"Start date '{start}' must be before end date '{end}'")

                if end_date > datetime.now():
                    logger.warning(
                        f"End date '{end}' is in the future, " f"using current date instead"
                    )

            except ValueError as e:
                if "does not match format" in str(e):
                    raise ValueError(
                        f"Invalid date format. Use YYYY-MM-DD. " f"Got start='{start}', end='{end}'"
                    ) from e
                raise

    def fetch_ticker(
        self,
        ticker: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "1y",
        interval: str = "1d",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Fetch historical data for a single ticker

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
            start: Start date (YYYY-MM-DD format)
            end: End date (YYYY-MM-DD format)
            period: Period to fetch (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
            use_cache: Whether to use cached data if available

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume, Adj Close

        Raises:
            ValueError: If ticker is invalid or parameters are incorrect
            ConnectionError: If network request fails
            RuntimeError: If Yahoo Finance API returns an error
        """
        ticker = ticker.upper()

        # Validate parameters
        self._validate_params(period, interval, start, end)

        # Validate ticker symbol
        if not self.validate_ticker(ticker):
            raise ValueError(
                f"Invalid or inaccessible ticker symbol: '{ticker}'. "
                f"Please verify the symbol exists."
            )

        cache_file = self._get_cache_filename(ticker, start, end, period, interval)

        # Check cache
        if use_cache and cache_file.exists():
            logger.info(f"Loading cached data for {ticker} from {cache_file}")
            try:
                return pd.read_csv(cache_file, index_col=0, parse_dates=True)
            except Exception as e:
                logger.warning(f"Failed to load cache for {ticker}: {e}")
                logger.info("Fetching fresh data instead")

        # Fetch from Yahoo Finance
        logger.info(f"Fetching data for {ticker} from Yahoo Finance")
        try:
            stock = yf.Ticker(ticker)

            if start and end:
                data = stock.history(start=start, end=end, interval=interval)
            else:
                data = stock.history(period=period, interval=interval)

            if data.empty:
                raise ValueError(
                    f"No data returned for ticker {ticker}. "
                    f"This may indicate an invalid ticker, delisted stock, "
                    f"or no data available for the specified period/interval."
                )

            # Save to cache
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                data.to_csv(cache_file)
                logger.info(f"Cached data saved to {cache_file}")
            except PermissionError:
                logger.warning(f"Permission denied writing cache to {cache_file}")
            except OSError as e:
                logger.warning(f"Failed to write cache: {e}")

            return data

        except ValueError:
            # Re-raise ValueError (ticker/param validation)
            raise
        except ConnectionError as e:
            logger.error(f"Network error fetching {ticker}: {e}")
            raise ConnectionError(
                f"Failed to connect to Yahoo Finance for {ticker}. "
                f"Check your internet connection."
            ) from e
        except Exception as e:
            error_msg = str(e).lower()

            # Detect specific error types
            if "404" in error_msg or "not found" in error_msg:
                raise ValueError(
                    f"Ticker '{ticker}' not found. " f"Verify the symbol is correct."
                ) from e
            elif "timeout" in error_msg:
                raise ConnectionError(
                    f"Request timeout for {ticker}. " f"Yahoo Finance may be slow or unreachable."
                ) from e
            elif "rate limit" in error_msg or "429" in error_msg:
                raise RuntimeError(
                    f"Yahoo Finance rate limit exceeded. "
                    f"Please wait a few minutes before retrying."
                ) from e
            else:
                logger.error(f"Unexpected error fetching {ticker}: {e}")
                raise RuntimeError(f"Failed to fetch data for {ticker}: {e}") from e

    def fetch_multiple_tickers(
        self,
        tickers: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "1y",
        interval: str = "1d",
        use_cache: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch data for multiple tickers

        Args:
            tickers: List of ticker symbols
            start: Start date (YYYY-MM-DD format)
            end: End date (YYYY-MM-DD format)
            period: Period to fetch
            interval: Data interval
            use_cache: Whether to use cached data

        Returns:
            Dictionary mapping ticker symbols to DataFrames
        """
        results = {}

        for ticker in tickers:
            try:
                results[ticker] = self.fetch_ticker(ticker, start, end, period, interval, use_cache)
            except Exception as e:
                logger.warning(f"Failed to fetch {ticker}: {e}")
                continue

        return results

    def get_ticker_info(self, ticker: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Get detailed information about a ticker

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data

        Returns:
            Dictionary with ticker metadata (empty dict if fetch fails)

        Note:
            Returns empty dict on failure rather than raising exception
            to allow other report sections to continue
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "info.json")

        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                logger.info(f"Loaded cached ticker info for {ticker}")
                return cached

        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            # Validate we got meaningful data
            if not info or len(info) < 5:
                logger.warning(
                    f"Minimal or no information returned for {ticker}. "
                    f"Ticker may be invalid or delisted."
                )
                return {}

            # Extract comprehensive fields
            result = {
                "symbol": ticker,
                "name": info.get("longName", "N/A"),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "market_cap": info.get("marketCap", None),
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange", "N/A"),
                "website": info.get("website", "N/A"),
                # Valuation metrics
                "pe_ratio": info.get("trailingPE", None),
                "forward_pe": info.get("forwardPE", None),
                "peg_ratio": info.get("pegRatio", None),
                "price_to_book": info.get("priceToBook", None),
                "price_to_sales": info.get("priceToSalesTrailing12Months", None),
                # Profitability
                "profit_margin": info.get("profitMargins", None),
                "operating_margin": info.get("operatingMargins", None),
                "roe": info.get("returnOnEquity", None),
                "roa": info.get("returnOnAssets", None),
                # Financial health
                "debt_to_equity": info.get("debtToEquity", None),
                "current_ratio": info.get("currentRatio", None),
                "quick_ratio": info.get("quickRatio", None),
                # Dividends
                "dividend_yield": info.get("dividendYield", None),
                "payout_ratio": info.get("payoutRatio", None),
                # Other
                "beta": info.get("beta", None),
                "52w_high": info.get("fiftyTwoWeekHigh", None),
                "52w_low": info.get("fiftyTwoWeekLow", None),
                "avg_volume": info.get("averageVolume", None),
            }

            # Cache the result
            try:
                self._save_json_cache(cache_file, result)
            except (PermissionError, OSError) as e:
                logger.warning(f"Failed to cache ticker info for {ticker}: {e}")

            return result

        except Exception as e:
            logger.error(f"Error fetching info for {ticker}: {e}")
            logger.info("Returning empty dict to allow other sections to continue")
            return {}

    def fetch_fundamentals(self, ticker: str, use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """
        Fetch fundamental financial statements

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data

        Returns:
            Dictionary with keys: 'income_stmt', 'balance_sheet', 'cash_flow'
            Each containing quarterly and annual DataFrames
        """
        keys = [
            "income_stmt_quarterly",
            "income_stmt_annual",
            "balance_sheet_quarterly",
            "balance_sheet_annual",
            "cash_flow_quarterly",
            "cash_flow_annual",
        ]

        def fetch_fn(stock):
            return {
                "income_stmt_quarterly": stock.quarterly_income_stmt,
                "income_stmt_annual": stock.income_stmt,
                "balance_sheet_quarterly": stock.quarterly_balance_sheet,
                "balance_sheet_annual": stock.balance_sheet,
                "cash_flow_quarterly": stock.quarterly_cashflow,
                "cash_flow_annual": stock.cashflow,
            }

        return self._fetch_resource(
            ticker=ticker,
            resource_name="fundamentals",
            cache_filename="fundamentals.json",
            fetch_fn=fetch_fn,
            serialize_fn=lambda r: {
                k: dataframe_to_json_dict(v) if not v.empty else {} for k, v in r.items()
            },
            deserialize_fn=lambda c: {k: pd.DataFrame(c.get(k, {})) for k in keys},
            empty_result={k: pd.DataFrame() for k in keys},
            use_cache=use_cache,
        )

    def fetch_earnings(self, ticker: str, use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """
        Fetch earnings history and upcoming earnings dates

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data

        Returns:
            Dictionary with 'earnings_history' and 'earnings_dates' DataFrames
        """
        keys = ["earnings_history", "earnings_dates"]

        def fetch_fn(stock):
            return {
                "earnings_history": (
                    stock.earnings_history if hasattr(stock, "earnings_history") else pd.DataFrame()
                ),
                "earnings_dates": (
                    stock.earnings_dates if hasattr(stock, "earnings_dates") else pd.DataFrame()
                ),
            }

        return self._fetch_resource(
            ticker=ticker,
            resource_name="earnings",
            cache_filename="earnings.json",
            fetch_fn=fetch_fn,
            serialize_fn=lambda r: {
                k: dataframe_to_records(v) if not v.empty else [] for k, v in r.items()
            },
            deserialize_fn=lambda c: {k: pd.DataFrame(c.get(k, {})) for k in keys},
            empty_result={k: pd.DataFrame() for k in keys},
            use_cache=use_cache,
        )

    def fetch_institutional_holders(
        self, ticker: str, use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch institutional and mutual fund holders

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data

        Returns:
            Dictionary with 'institutional_holders' and 'mutualfund_holders'
        """
        keys = ["institutional_holders", "mutualfund_holders"]

        def fetch_fn(stock):
            return {
                "institutional_holders": stock.institutional_holders,
                "mutualfund_holders": stock.mutualfund_holders,
            }

        return self._fetch_resource(
            ticker=ticker,
            resource_name="holders",
            cache_filename="holders.json",
            fetch_fn=fetch_fn,
            serialize_fn=lambda r: {
                k: dataframe_to_records(v, preserve_index=False) if not v.empty else []
                for k, v in r.items()
            },
            deserialize_fn=lambda c: {k: pd.DataFrame(c.get(k, {})) for k in keys},
            empty_result={k: pd.DataFrame() for k in keys},
            use_cache=use_cache,
        )

    def fetch_dividends(self, ticker: str, use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """
        Fetch dividend and stock split history

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data

        Returns:
            Dictionary with 'dividends', 'splits', and 'actions' DataFrames
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "dividends.json")

        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return {
                    "dividends": pd.DataFrame(cached.get("dividends", {})),
                    "splits": pd.DataFrame(cached.get("splits", {})),
                    "actions": pd.DataFrame(cached.get("actions", {})),
                }

        try:
            logger.info(f"Fetching dividends for {ticker}")
            stock = yf.Ticker(ticker)

            # Get data and convert Series to DataFrame if needed
            dividends_data = getattr(stock, "dividends", pd.Series())
            splits_data = getattr(stock, "splits", pd.Series())
            actions_data = getattr(stock, "actions", pd.DataFrame())

            # Convert Series to DataFrame using utility
            dividends_df = (
                series_to_dataframe(dividends_data, "Dividends", "Date")
                if isinstance(dividends_data, pd.Series)
                else pd.DataFrame()
            )
            splits_df = (
                series_to_dataframe(splits_data, "Stock Splits", "Date")
                if isinstance(splits_data, pd.Series)
                else pd.DataFrame()
            )

            if not isinstance(actions_data, pd.DataFrame):
                actions_df = pd.DataFrame()
            else:
                actions_df = actions_data
                if not actions_df.empty:
                    actions_df.index.name = "Date"

            result = {
                "dividends": dividends_df,
                "splits": splits_df,
                "actions": actions_df,
            }

            # Cache as JSON using serialization utility
            cache_data = {
                k: dataframe_to_records(v) if not v.empty else [] for k, v in result.items()
            }

            self._save_json_cache(cache_file, cache_data)

            return result

        except Exception as e:
            logger.error(f"Error fetching dividends for {ticker}: {e}")
            return {
                "dividends": pd.DataFrame(),
                "splits": pd.DataFrame(),
                "actions": pd.DataFrame(),
            }

    def fetch_analyst_ratings(self, ticker: str, use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """
        Fetch analyst recommendations and price targets

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data

        Returns:
            Dictionary with 'recommendations' and 'upgrades_downgrades' DataFrames
        """
        keys = ["recommendations", "upgrades_downgrades"]

        def fetch_fn(stock):
            recommendations_data = getattr(stock, "recommendations", None)
            upgrades_data = getattr(stock, "upgrades_downgrades", None)
            return {
                "recommendations": (
                    recommendations_data
                    if isinstance(recommendations_data, pd.DataFrame)
                    else pd.DataFrame()
                ),
                "upgrades_downgrades": (
                    upgrades_data if isinstance(upgrades_data, pd.DataFrame) else pd.DataFrame()
                ),
            }

        return self._fetch_resource(
            ticker=ticker,
            resource_name="analyst ratings",
            cache_filename="analyst_ratings.json",
            fetch_fn=fetch_fn,
            serialize_fn=lambda r: {
                k: dataframe_to_records(v) if not v.empty else [] for k, v in r.items()
            },
            deserialize_fn=lambda c: {k: pd.DataFrame(c.get(k, {})) for k in keys},
            empty_result={k: pd.DataFrame() for k in keys},
            use_cache=use_cache,
        )

    def fetch_news(
        self, ticker: str, use_cache: bool = False  # News is time-sensitive, default to fresh
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent news articles for a ticker

        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data (default False for time-sensitive news)

        Returns:
            List of news article dictionaries with title, publisher, link, etc.
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "news.json")

        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return cached

        try:
            logger.info(f"Fetching news for {ticker}")
            stock = yf.Ticker(ticker)

            # Get news safely
            news_data = getattr(stock, "news", [])
            news = news_data if isinstance(news_data, list) else []

            # Cache the result
            self._save_json_cache(cache_file, news)

            return news

        except Exception as e:
            logger.error(f"Error fetching news for {ticker}: {e}")
            return []

    # ==================== Cache Helper Methods ====================

    def _get_cache_file_path(self, ticker: str, filename: str) -> Path:
        """
        Get cache file path and ensure directory exists

        Args:
            ticker: Stock ticker symbol
            filename: Name of cache file (e.g., 'info.json', 'fundamentals.json')

        Returns:
            Path object for the cache file
        """
        cache_dir = self.cache_dir / ticker / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / filename

    def _load_json_cache(self, cache_path: Path) -> Optional[Any]:
        """
        Load data from JSON cache file if it exists

        Args:
            cache_path: Path to cache file

        Returns:
            Cached data or None if cache doesn't exist or is invalid
        """
        if not cache_path.exists():
            return None

        try:
            logger.info(f"Loading from cache: {cache_path}")
            with open(cache_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in cache file {cache_path}: {e}")
            logger.info("Cache will be regenerated")
            return None
        except PermissionError:
            logger.warning(f"Permission denied reading cache: {cache_path}")
            return None
        except OSError as e:
            logger.warning(f"OS error reading cache {cache_path}: {e}")
            return None

    def _save_json_cache(self, cache_path: Path, data: Any) -> None:
        """
        Save data to JSON cache file with error handling

        Args:
            cache_path: Path to cache file
            data: Data to cache (must be JSON-serializable)

        Note:
            Logs warnings on failure but does not raise exceptions
            to avoid breaking the main fetch operations
        """
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Saved to cache: {cache_path}")
        except PermissionError:
            logger.warning(f"Permission denied writing cache to {cache_path}")
        except OSError as e:
            logger.warning(f"OS error saving cache to {cache_path}: {e}")
        except TypeError as e:
            logger.warning(f"Data not JSON-serializable for {cache_path}: {e}")

    # ==================== Fetch Template ====================

    def _fetch_resource(
        self,
        ticker: str,
        resource_name: str,
        cache_filename: str,
        fetch_fn: Callable[[yf.Ticker], Dict[str, pd.DataFrame]],
        serialize_fn: Callable[[Dict[str, pd.DataFrame]], Any],
        deserialize_fn: Callable[[Any], Dict[str, pd.DataFrame]],
        empty_result: Dict[str, pd.DataFrame],
        use_cache: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """
        Generic template for fetching and caching financial data resources

        Args:
            ticker: Stock ticker symbol
            resource_name: Human-readable name for logging
            cache_filename: Cache file name (e.g., 'fundamentals.json')
            fetch_fn: Function that fetches data from yfinance Ticker
            serialize_fn: Function to serialize data for caching
            deserialize_fn: Function to deserialize cached data
            empty_result: Default empty result on failure
            use_cache: Whether to use cached data

        Returns:
            Dictionary with fetched data
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, cache_filename)

        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return deserialize_fn(cached)

        try:
            logger.info(f"Fetching {resource_name} for {ticker}")
            stock = yf.Ticker(ticker)
            result = fetch_fn(stock)
            cache_data = serialize_fn(result)
            self._save_json_cache(cache_file, cache_data)
            return result

        except Exception as e:
            logger.error(f"Error fetching {resource_name} for {ticker}: {e}")
            return empty_result

    # ==================== Legacy Methods ====================

    def _get_cache_filename(
        self, ticker: str, start: Optional[str], end: Optional[str], period: str, interval: str
    ) -> Path:
        """Generate cache filename based on parameters (for CSV price data)"""
        # Create cache subdirectory
        cache_dir = self.cache_dir / ticker / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        if start and end:
            filename = f"prices_{start}_{end}_{interval}.csv"
        else:
            filename = f"prices_{period}_{interval}.csv"
        return cache_dir / filename

    def clear_cache(self, ticker: Optional[str] = None):
        """
        Clear cached data

        Args:
            ticker: If specified, only clear cache for this ticker. Otherwise clear all.
        """
        if ticker:
            ticker = ticker.upper()
            ticker_dir = self.cache_dir / ticker
            if ticker_dir.exists():
                import shutil

                shutil.rmtree(ticker_dir)
                logger.info(f"Deleted cache directory: {ticker_dir}")
        else:
            import shutil

            for ticker_dir in self.cache_dir.iterdir():
                if ticker_dir.is_dir():
                    shutil.rmtree(ticker_dir)
            logger.info("Cleared all cache directories")
