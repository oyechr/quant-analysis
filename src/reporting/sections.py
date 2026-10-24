"""
Report Section Handlers
Modular handlers for different data sections in reports
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd

from ..analysis.fundamental import FundamentalAnalyzer
from ..analysis.valuation import ValuationAnalyzer

logger = logging.getLogger(__name__)


class ReportSection(ABC):
    """Base class for report sections"""

    @abstractmethod
    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        """
        Fetch raw data for this section

        Args:
            fetcher: DataFetcher instance
            ticker: Stock ticker symbol
            use_cache: Whether to use cached data
            **kwargs: Additional parameters

        Returns:
            Dictionary with raw data
        """
        pass

    @abstractmethod
    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format data for JSON output

        Args:
            raw_data: Raw data from fetch_data

        Returns:
            JSON-serializable dictionary
        """
        pass


class InfoSection(ReportSection):
    """Company information section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching info for {ticker}")
        info: Dict[str, Any] = fetcher.get_ticker_info(ticker, use_cache=use_cache)
        return info

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class PriceDataSection(ReportSection):
    """Price data section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching price data for {ticker}")
        period = kwargs.get("period", "1mo")
        try:
            price_data = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)
            return {
                "shape": price_data.shape,
                "date_range": {"start": str(price_data.index[0]), "end": str(price_data.index[-1])},
                "latest": {
                    "date": str(price_data.index[-1]),
                    "open": float(price_data["Open"].iloc[-1]),
                    "high": float(price_data["High"].iloc[-1]),
                    "low": float(price_data["Low"].iloc[-1]),
                    "close": float(price_data["Close"].iloc[-1]),
                    "volume": int(price_data["Volume"].iloc[-1]),
                },
                "statistics": {
                    "high_52w": float(price_data["High"].max()),
                    "low_52w": float(price_data["Low"].min()),
                    "avg_volume": float(price_data["Volume"].mean()),
                    "volatility": float(price_data["Close"].pct_change().std()),
                },
            }
        except Exception as e:
            logger.warning(f"Could not fetch price data: {e}")
            return {}

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class FundamentalsSection(ReportSection):
    """Fundamentals section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching fundamentals for {ticker}")
        fundamentals = fetcher.fetch_fundamentals(ticker, use_cache=use_cache)
        return {k: {"shape": v.shape, "has_data": not v.empty} for k, v in fundamentals.items()}

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class EarningsSection(ReportSection):
    """Earnings section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching earnings for {ticker}")
        earnings = fetcher.fetch_earnings(ticker, use_cache=use_cache)
        return {
            "history_count": len(earnings["earnings_history"]),
            "dates_count": len(earnings["earnings_dates"]),
            "latest_earnings": (
                earnings["earnings_history"]
                .head(3)
                .reset_index()
                .replace({float("nan"): None})
                .to_dict("records")
                if not earnings["earnings_history"].empty
                else []
            ),
            "upcoming_dates": (
                earnings["earnings_dates"]
                .head(3)
                .reset_index()
                .replace({float("nan"): None})
                .to_dict("records")
                if not earnings["earnings_dates"].empty
                else []
            ),
        }

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class HoldersSection(ReportSection):
    """Institutional holders section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching holders for {ticker}")
        holders = fetcher.fetch_institutional_holders(ticker, use_cache=use_cache)
        return {
            "institutional_count": len(holders["institutional_holders"]),
            "mutualfund_count": len(holders["mutualfund_holders"]),
            "top_institutional": (
                holders["institutional_holders"]
                .head(5)
                .replace({float("nan"): None})
                .to_dict("records")
                if not holders["institutional_holders"].empty
                else []
            ),
            "top_mutualfund": (
                holders["mutualfund_holders"]
                .head(5)
                .replace({float("nan"): None})
                .to_dict("records")
                if not holders["mutualfund_holders"].empty
                else []
            ),
        }

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class DividendsSection(ReportSection):
    """Dividends and stock splits section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching dividends for {ticker}")
        dividends = fetcher.fetch_dividends(ticker, use_cache=use_cache)
        return {
            "dividend_count": len(dividends["dividends"]),
            "split_count": len(dividends["splits"]),
            "recent_dividends": (
                dividends["dividends"]
                .tail(10)
                .reset_index()
                .replace({float("nan"): None})
                .to_dict("records")
                if not dividends["dividends"].empty
                else []
            ),
            "recent_splits": (
                dividends["splits"]
                .tail(5)
                .reset_index()
                .replace({float("nan"): None})
                .to_dict("records")
                if not dividends["splits"].empty
                else []
            ),
        }

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class AnalystRatingsSection(ReportSection):
    """Analyst ratings section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching analyst ratings for {ticker}")
        analyst = fetcher.fetch_analyst_ratings(ticker, use_cache=use_cache)
        return {
            "recommendation_count": len(analyst["recommendations"]),
            "upgrade_downgrade_count": len(analyst["upgrades_downgrades"]),
            "recent_recommendations": (
                analyst["recommendations"].head(10).replace({float("nan"): None}).to_dict("records")
                if not analyst["recommendations"].empty
                else []
            ),
            "recent_changes": (
                analyst["upgrades_downgrades"]
                .head(10)
                .replace({float("nan"): None})
                .to_dict("records")
                if not analyst["upgrades_downgrades"].empty
                else []
            ),
        }

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class NewsSection(ReportSection):
    """News section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching news for {ticker}")
        news = fetcher.fetch_news(ticker, use_cache=False)  # Always fresh
        return {"article_count": len(news), "recent_articles": news[:10] if news else []}

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class TechnicalAnalysisSection(ReportSection):
    """Technical analysis section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Any:
        """Fetch price data and calculate technical indicators"""
        from ..analysis.technical import TechnicalAnalyzer

        # Fetch 1 year of data for 200-day SMA calculation
        period = kwargs.get("period", "1y")
        price_data = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)

        # Get currency from ticker info
        ticker_info = fetcher.get_ticker_info(ticker, use_cache=use_cache)
        currency = ticker_info.get("currency", "USD")

        # Calculate all indicators
        analyzer = TechnicalAnalyzer(price_data, currency=currency)
        analyzer.calculate_all_indicators()

        # Return analyzer instance for formatting
        return analyzer

    def format_for_json(self, raw_data: Any) -> Any:
        """Format technical analysis for JSON (return summary)"""
        if hasattr(raw_data, "get_summary"):
            return raw_data.get_summary()
        return None


class FundamentalAnalysisSection(ReportSection):
    """Handle fundamental analysis data"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Any:
        """
        Fetch financial data and create analyzer

        Returns:
            FundamentalAnalyzer instance (not dict - for dual formatting)
        """
        # Fetch required data
        ticker_info = fetcher.get_ticker_info(ticker, use_cache=use_cache)
        fundamentals = fetcher.fetch_fundamentals(ticker, use_cache=use_cache)
        price_data = kwargs.get("price_data")  # Optional, passed from generator

        # Create analyzer
        analyzer = FundamentalAnalyzer(ticker_info, fundamentals, price_data)
        return analyzer

    def format_for_json(self, raw_data: Any) -> Any:
        """Format for JSON - use analyzer's get_summary()"""
        if hasattr(raw_data, "get_summary"):
            return raw_data.get_summary()
        return None


class RiskAnalysisSection(ReportSection):
    """Handle risk metrics and performance analysis"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Any:
        """
        Calculate risk metrics

        Returns:
            Tuple of (RiskMetrics instance, metrics dict, benchmark_data)
        """
        from ..analysis.risk import RiskMetrics
        from ..config import get_config
        from ..markets import benchmark_for

        period = kwargs.get("period", "1y")
        price_data = kwargs.get("price_data")
        if price_data is None or price_data.empty:
            price_data = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)

        # Benchmark against the ticker's home market (e.g. OSEBX for .OL listings)
        benchmark_ticker = kwargs.get("benchmark_ticker") or benchmark_for(ticker)
        benchmark_data = kwargs.get("benchmark_data")
        if not isinstance(benchmark_data, pd.DataFrame) or benchmark_data.empty:
            # Use period= (not start=/end=) so the cache filename is stable across days.
            # start/end shift daily, causing a fresh fetch every run.
            try:
                benchmark_data = fetcher.fetch_ticker(
                    benchmark_ticker, period=period, use_cache=use_cache
                )
            except Exception as e:
                default_benchmark = get_config().benchmark_ticker
                if benchmark_ticker == default_benchmark:
                    raise
                logger.warning(
                    f"Benchmark {benchmark_ticker} unavailable ({e}); "
                    f"falling back to {default_benchmark}"
                )
                benchmark_ticker = default_benchmark
                benchmark_data = fetcher.fetch_ticker(
                    benchmark_ticker, period=period, use_cache=use_cache
                )

        # Calculate all metrics (pass benchmark to avoid re-fetch)
        risk_analyzer = RiskMetrics(benchmark_ticker=benchmark_ticker)
        metrics = risk_analyzer.calculate_all_metrics(price_data, benchmark_data=benchmark_data)

        # Return tuple: (analyzer, metrics, benchmark) for dual formatting
        return (risk_analyzer, metrics, benchmark_data)

    def format_for_json(self, raw_data: Any) -> Any:
        """Format risk metrics for JSON"""
        if isinstance(raw_data, tuple) and len(raw_data) >= 2:
            _, metrics, _ = raw_data
            return metrics
        return None


class ValuationAnalysisSection(ReportSection):
    """Valuation analysis section (DCF, DDM, dividends, earnings)"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Performing valuation analysis for {ticker}")

        # Fetch required data
        info = fetcher.get_ticker_info(ticker, use_cache=use_cache)
        price_data = kwargs.get("price_data")
        fundamentals = fetcher.fetch_fundamentals(ticker, use_cache=use_cache)
        earnings_data = fetcher.fetch_earnings(ticker, use_cache=use_cache)
        dividends_data = kwargs.get("dividends_data")

        # Create analyzer
        analyzer = ValuationAnalyzer(
            ticker=ticker,
            ticker_info=info,
            price_data=price_data,
            fundamentals=fundamentals,
            earnings_data=earnings_data,
            dividends_data=dividends_data,
        )

        # Run analysis
        return analyzer.analyze()

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format valuation data for JSON"""
        return raw_data  # Already in good format
