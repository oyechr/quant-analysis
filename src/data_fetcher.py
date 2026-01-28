"""
Data Fetcher Module
Handles fetching historical market data from Yahoo Finance
"""

import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Union
import logging

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
        period: str = "1y",
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
        period: str = "1y",
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
    
    def get_ticker_info(self, ticker: str) -> dict:
        """
        Get detailed information about a ticker
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Dictionary with ticker metadata
        """
        try:
            stock = yf.Ticker(ticker.upper())
            info = stock.info
            
            # Extract key fields
            return {
                'symbol': ticker.upper(),
                'name': info.get('longName', 'N/A'),
                'sector': info.get('sector', 'N/A'),
                'industry': info.get('industry', 'N/A'),
                'market_cap': info.get('marketCap', None),
                'currency': info.get('currency', 'USD'),
                'exchange': info.get('exchange', 'N/A'),
                'website': info.get('website', 'N/A'),
            }
        except Exception as e:
            logger.error(f"Error fetching info for {ticker}: {e}")
            return {}
    
    def _get_cache_filename(
        self,
        ticker: str,
        start: Optional[str],
        end: Optional[str],
        period: str,
        interval: str
    ) -> Path:
        """Generate cache filename based on parameters"""
        if start and end:
            filename = f"{ticker}_{start}_{end}_{interval}.csv"
        else:
            filename = f"{ticker}_{period}_{interval}.csv"
        return self.cache_dir / filename
    
    def clear_cache(self, ticker: Optional[str] = None):
        """
        Clear cached data
        
        Args:
            ticker: If specified, only clear cache for this ticker. Otherwise clear all.
        """
        if ticker:
            pattern = f"{ticker.upper()}_*.csv"
            for file in self.cache_dir.glob(pattern):
                file.unlink()
                logger.info(f"Deleted cache file: {file}")
        else:
            for file in self.cache_dir.glob("*.csv"):
                file.unlink()
            logger.info("Cleared all cache files")


# Convenience functions
def fetch_ticker(ticker: str, period: str = "1y", **kwargs) -> pd.DataFrame:
    """Quick fetch for a single ticker"""
    fetcher = DataFetcher()
    return fetcher.fetch_ticker(ticker, period=period, **kwargs)


def fetch_multiple(tickers: List[str], period: str = "1y", **kwargs) -> dict[str, pd.DataFrame]:
    """Quick fetch for multiple tickers"""
    fetcher = DataFetcher()
    return fetcher.fetch_multiple_tickers(tickers, period=period, **kwargs)
