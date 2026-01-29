"""
Data Fetcher Module
Handles fetching historical market data from Yahoo Finance
"""

import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Union, Dict, Any
import logging
import json

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
        
    def fetch_ticker(
        self,
        ticker: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "1mo",
        interval: str = "1d",
        use_cache: bool = True
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
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_filename(ticker, start, end, period, interval)
        
        # Check cache
        if use_cache and cache_file.exists():
            logger.info(f"Loading cached data for {ticker} from {cache_file}")
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)
        
        # Fetch from Yahoo Finance
        logger.info(f"Fetching data for {ticker} from Yahoo Finance")
        try:
            stock = yf.Ticker(ticker)
            
            if start and end:
                data = stock.history(start=start, end=end, interval=interval)
            else:
                data = stock.history(period=period, interval=interval)
            
            if data.empty:
                raise ValueError(f"No data returned for ticker {ticker}")
            
            # Save to cache
            data.to_csv(cache_file)
            logger.info(f"Cached data saved to {cache_file}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching data for {ticker}: {e}")
            raise
    
    def fetch_multiple_tickers(
        self,
        tickers: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "1mo",
        interval: str = "1d",
        use_cache: bool = True
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
                results[ticker] = self.fetch_ticker(
                    ticker, start, end, period, interval, use_cache
                )
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
            Dictionary with ticker metadata
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "info.json")
        
        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return cached
        
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Extract comprehensive fields
            result = {
                'symbol': ticker,
                'name': info.get('longName', 'N/A'),
                'sector': info.get('sector', 'N/A'),
                'industry': info.get('industry', 'N/A'),
                'market_cap': info.get('marketCap', None),
                'currency': info.get('currency', 'USD'),
                'exchange': info.get('exchange', 'N/A'),
                'website': info.get('website', 'N/A'),
                # Valuation metrics
                'pe_ratio': info.get('trailingPE', None),
                'forward_pe': info.get('forwardPE', None),
                'peg_ratio': info.get('pegRatio', None),
                'price_to_book': info.get('priceToBook', None),
                'price_to_sales': info.get('priceToSalesTrailing12Months', None),
                # Profitability
                'profit_margin': info.get('profitMargins', None),
                'operating_margin': info.get('operatingMargins', None),
                'roe': info.get('returnOnEquity', None),
                'roa': info.get('returnOnAssets', None),
                # Financial health
                'debt_to_equity': info.get('debtToEquity', None),
                'current_ratio': info.get('currentRatio', None),
                'quick_ratio': info.get('quickRatio', None),
                # Dividends
                'dividend_yield': info.get('dividendYield', None),
                'payout_ratio': info.get('payoutRatio', None),
                # Other
                'beta': info.get('beta', None),
                '52w_high': info.get('fiftyTwoWeekHigh', None),
                '52w_low': info.get('fiftyTwoWeekLow', None),
                'avg_volume': info.get('averageVolume', None),
            }
            
            # Cache the result
            self._save_json_cache(cache_file, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching info for {ticker}: {e}")
            return {}
    
    def fetch_fundamentals(
        self,
        ticker: str,
        use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch fundamental financial statements
        
        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with keys: 'income_stmt', 'balance_sheet', 'cash_flow'
            Each containing quarterly and annual DataFrames
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "fundamentals.json")
        
        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return {
                    'income_stmt_quarterly': pd.DataFrame(cached['income_stmt_quarterly']),
                    'income_stmt_annual': pd.DataFrame(cached['income_stmt_annual']),
                    'balance_sheet_quarterly': pd.DataFrame(cached['balance_sheet_quarterly']),
                    'balance_sheet_annual': pd.DataFrame(cached['balance_sheet_annual']),
                    'cash_flow_quarterly': pd.DataFrame(cached['cash_flow_quarterly']),
                    'cash_flow_annual': pd.DataFrame(cached['cash_flow_annual']),
                }
        
        try:
            logger.info(f"Fetching fundamentals for {ticker}")
            stock = yf.Ticker(ticker)
            
            result = {
                'income_stmt_quarterly': stock.quarterly_income_stmt,
                'income_stmt_annual': stock.income_stmt,
                'balance_sheet_quarterly': stock.quarterly_balance_sheet,
                'balance_sheet_annual': stock.balance_sheet,
                'cash_flow_quarterly': stock.quarterly_cashflow,
                'cash_flow_annual': stock.cashflow,
            }
            
            # Cache as JSON (convert DataFrames to dict, handle Timestamps and NaN)
            cache_data = {}
            for k, v in result.items():
                if not v.empty:
                    # Replace NaN with None first
                    v_clean = v.replace({float('nan'): None})
                    # Convert to dict with string columns (handles Timestamps)
                    df_dict = v_clean.to_dict()
                    # Convert Timestamp keys to strings and handle None values
                    cache_data[k] = {
                        str(key): {str(inner_key): val if val is not None else None for inner_key, val in inner_dict.items()}
                        for key, inner_dict in df_dict.items()
                    }
                else:
                    cache_data[k] = {}
            
            self._save_json_cache(cache_file, cache_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {ticker}: {e}")
            return {
                'income_stmt_quarterly': pd.DataFrame(),
                'income_stmt_annual': pd.DataFrame(),
                'balance_sheet_quarterly': pd.DataFrame(),
                'balance_sheet_annual': pd.DataFrame(),
                'cash_flow_quarterly': pd.DataFrame(),
                'cash_flow_annual': pd.DataFrame(),
            }
    
    def fetch_earnings(
        self,
        ticker: str,
        use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch earnings history and upcoming earnings dates
        
        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with 'earnings_history' and 'earnings_dates' DataFrames
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "earnings.json")
        
        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return {
                    'earnings_history': pd.DataFrame(cached.get('earnings_history', {})),
                    'earnings_dates': pd.DataFrame(cached.get('earnings_dates', {})),
                }
        
        try:
            logger.info(f"Fetching earnings for {ticker}")
            stock = yf.Ticker(ticker)
            
            result = {
                'earnings_history': stock.earnings_history if hasattr(stock, 'earnings_history') else pd.DataFrame(),
                'earnings_dates': stock.earnings_dates if hasattr(stock, 'earnings_dates') else pd.DataFrame(),
            }
            
            # Cache as JSON (handle Timestamps in columns/index)
            cache_data = {}
            for k, v in result.items():
                if not v.empty:
                    # Reset index to handle Timestamp indices
                    df_reset = v.reset_index()
                    # Convert ALL object columns that might contain Timestamps
                    for col in df_reset.columns:
                        if df_reset[col].dtype == 'object' or pd.api.types.is_datetime64_any_dtype(df_reset[col]):
                            df_reset[col] = df_reset[col].astype(str)
                    # Replace NaN with None for valid JSON
                    cache_data[k] = df_reset.replace({float('nan'): None}).to_dict('records')
                else:
                    cache_data[k] = []
            
            self._save_json_cache(cache_file, cache_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching earnings for {ticker}: {e}")
            return {
                'earnings_history': pd.DataFrame(),
                'earnings_dates': pd.DataFrame(),
            }
    
    def fetch_institutional_holders(
        self,
        ticker: str,
        use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch institutional and mutual fund holders
        
        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with 'institutional_holders' and 'mutualfund_holders'
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "holders.json")
        
        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return {
                    'institutional_holders': pd.DataFrame(cached.get('institutional_holders', {})),
                    'mutualfund_holders': pd.DataFrame(cached.get('mutualfund_holders', {})),
                }
        
        try:
            logger.info(f"Fetching holders for {ticker}")
            stock = yf.Ticker(ticker)
            
            result = {
                'institutional_holders': stock.institutional_holders,
                'mutualfund_holders': stock.mutualfund_holders,
            }
            
            # Cache as JSON (handle Timestamps in columns/index)
            cache_data = {}
            for k, v in result.items():
                if not v.empty:
                    # Reset index to handle Timestamp indices
                    df_reset = v.reset_index()
                    # Convert all datetime columns to strings
                    for col in df_reset.select_dtypes(include=['datetime64']).columns:
                        df_reset[col] = df_reset[col].astype(str)
                    # Replace NaN with None for valid JSON
                    cache_data[k] = df_reset.replace({float('nan'): None}).to_dict('records')
                else:
                    cache_data[k] = []
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"Cached holders for {ticker}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching holders for {ticker}: {e}")
            return {
                'institutional_holders': pd.DataFrame(),
                'mutualfund_holders': pd.DataFrame(),
            }
    
    def fetch_dividends(
        self,
        ticker: str,
        use_cache: bool = True
    ) -> Dict[str, Any]:
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
                    'dividends': pd.DataFrame(cached.get('dividends', {})),
                    'splits': pd.DataFrame(cached.get('splits', {})),
                    'actions': pd.DataFrame(cached.get('actions', {})),
                }
        
        try:
            logger.info(f"Fetching dividends for {ticker}")
            stock = yf.Ticker(ticker)
            
            # Get data and convert Series to DataFrame if needed
            dividends_data = getattr(stock, 'dividends', pd.Series())
            splits_data = getattr(stock, 'splits', pd.Series())
            actions_data = getattr(stock, 'actions', pd.DataFrame())
            
            # Convert Series to DataFrame for consistency
            if isinstance(dividends_data, pd.Series) and not dividends_data.empty:
                dividends_df = dividends_data.to_frame(name='Dividends')
                dividends_df.index.name = 'Date'  # Preserve index name
            else:
                dividends_df = pd.DataFrame()
            
            if isinstance(splits_data, pd.Series) and not splits_data.empty:
                splits_df = splits_data.to_frame(name='Stock Splits')
                splits_df.index.name = 'Date'  # Preserve index name
            else:
                splits_df = pd.DataFrame()
            
            if not isinstance(actions_data, pd.DataFrame):
                actions_df = pd.DataFrame()
            else:
                actions_df = actions_data
                if not actions_df.empty:
                    actions_df.index.name = 'Date'  # Preserve index name
            
            result = {
                'dividends': dividends_df,
                'splits': splits_df,
                'actions': actions_df,
            }
            
            # Cache as JSON
            cache_data = {}
            for k, v in result.items():
                if not v.empty:
                    # Reset index to handle Timestamp indices
                    df_reset = v.reset_index()
                    # Convert datetime columns to strings
                    for col in df_reset.select_dtypes(include=['datetime64']).columns:
                        df_reset[col] = df_reset[col].astype(str)
                    # Replace NaN with None for valid JSON
                    cache_data[k] = df_reset.replace({float('nan'): None}).to_dict('records')
                else:
                    cache_data[k] = []
            
            self._save_json_cache(cache_file, cache_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching dividends for {ticker}: {e}")
            return {
                'dividends': pd.DataFrame(),
                'splits': pd.DataFrame(),
                'actions': pd.DataFrame(),
            }
    
    def fetch_analyst_ratings(
        self,
        ticker: str,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Fetch analyst recommendations and price targets
        
        Args:
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with 'recommendations' and 'upgrades_downgrades' DataFrames
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file_path(ticker, "analyst_ratings.json")
        
        # Check cache
        if use_cache:
            cached = self._load_json_cache(cache_file)
            if cached is not None:
                return {
                    'recommendations': pd.DataFrame(cached.get('recommendations', {})),
                    'upgrades_downgrades': pd.DataFrame(cached.get('upgrades_downgrades', {})),
                }
        
        try:
            logger.info(f"Fetching analyst ratings for {ticker}")
            stock = yf.Ticker(ticker)
            
            # Get data safely
            recommendations_data = getattr(stock, 'recommendations', None)
            upgrades_data = getattr(stock, 'upgrades_downgrades', None)
            
            # Ensure we have DataFrames
            recommendations_df = recommendations_data if isinstance(recommendations_data, pd.DataFrame) else pd.DataFrame()
            upgrades_df = upgrades_data if isinstance(upgrades_data, pd.DataFrame) else pd.DataFrame()
            
            result = {
                'recommendations': recommendations_df,
                'upgrades_downgrades': upgrades_df,
            }
            
            # Cache as JSON
            cache_data = {}
            for k, v in result.items():
                if not v.empty:
                    # Reset index to handle Timestamp indices
                    df_reset = v.reset_index()
                    # Convert all object columns that might contain Timestamps
                    for col in df_reset.columns:
                        if df_reset[col].dtype == 'object' or pd.api.types.is_datetime64_any_dtype(df_reset[col]):
                            df_reset[col] = df_reset[col].astype(str)
                    # Replace NaN with None for valid JSON
                    cache_data[k] = df_reset.replace({float('nan'): None}).to_dict('records')
                else:
                    cache_data[k] = []
            
            self._save_json_cache(cache_file, cache_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching analyst ratings for {ticker}: {e}")
            return {
                'recommendations': pd.DataFrame(),
                'upgrades_downgrades': pd.DataFrame(),
            }
    
    def fetch_news(
        self,
        ticker: str,
        use_cache: bool = False  # News is time-sensitive, default to fresh
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
            news_data = getattr(stock, 'news', [])
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
        ticker_dir = self.cache_dir / ticker
        ticker_dir.mkdir(exist_ok=True)
        return ticker_dir / filename
    
    def _load_json_cache(self, cache_path: Path) -> Optional[Any]:
        """
        Load data from JSON cache file if it exists
        
        Args:
            cache_path: Path to cache file
            
        Returns:
            Cached data or None if cache doesn't exist
        """
        if cache_path.exists():
            logger.info(f"Loading from cache: {cache_path}")
            with open(cache_path, 'r') as f:
                return json.load(f)
        return None
    
    def _save_json_cache(self, cache_path: Path, data: Any) -> None:
        """
        Save data to JSON cache file
        
        Args:
            cache_path: Path to cache file
            data: Data to cache (must be JSON-serializable)
        """
        with open(cache_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved to cache: {cache_path}")
    
    # ==================== Legacy Methods ====================
    
    def _get_cache_filename(
        self,
        ticker: str,
        start: Optional[str],
        end: Optional[str],
        period: str,
        interval: str
    ) -> Path:
        """Generate cache filename based on parameters (for CSV price data)"""
        # Create ticker-specific subdirectory
        ticker_dir = self.cache_dir / ticker
        ticker_dir.mkdir(exist_ok=True)
        
        if start and end:
            filename = f"{start}_{end}_{interval}.csv"
        else:
            filename = f"{period}_{interval}.csv"
        return ticker_dir / filename
    
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


# Convenience functions
def fetch_ticker(ticker: str, period: str = "1mo", **kwargs) -> pd.DataFrame:
    """Quick fetch for a single ticker"""
    fetcher = DataFetcher()
    return fetcher.fetch_ticker(ticker, period=period, **kwargs)


def fetch_multiple(tickers: List[str], period: str = "1mo", **kwargs) -> dict[str, pd.DataFrame]:
    """Quick fetch for multiple tickers"""
    fetcher = DataFetcher()
    return fetcher.fetch_multiple_tickers(tickers, period=period, **kwargs)
