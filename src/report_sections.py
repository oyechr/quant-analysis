"""
Report Section Handlers
Modular handlers for different data sections in reports
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import pandas as pd

from .fundamental_analysis import FundamentalAnalyzer

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

    @abstractmethod
    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        """
        Format data as markdown lines

        Args:
            raw_data: Raw data from fetch_data

        Returns:
            List of markdown lines
        """
        pass


class InfoSection(ReportSection):
    """Company information section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching info for {ticker}")
        return fetcher.get_ticker_info(ticker, use_cache=use_cache)

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Company Information")
        md.append(f"\n- **Name:** {raw_data.get('name', 'N/A')}")
        md.append(f"- **Sector:** {raw_data.get('sector', 'N/A')}")
        md.append(f"- **Industry:** {raw_data.get('industry', 'N/A')}")
        md.append(f"- **Exchange:** {raw_data.get('exchange', 'N/A')}")
        md.append(f"- **Currency:** {raw_data.get('currency', 'N/A')}")
        if raw_data.get("website") != "N/A":
            md.append(f"- **Website:** {raw_data.get('website')}")

        md.append("\n## Valuation Metrics")
        md.append(f"\n- **Market Cap:** {self._format_number(raw_data.get('market_cap'))}")
        md.append(f"- **P/E Ratio:** {self._format_number(raw_data.get('pe_ratio'))}")
        md.append(f"- **Forward P/E:** {self._format_number(raw_data.get('forward_pe'))}")
        md.append(f"- **PEG Ratio:** {self._format_number(raw_data.get('peg_ratio'))}")
        md.append(f"- **Price/Book:** {self._format_number(raw_data.get('price_to_book'))}")
        md.append(f"- **Price/Sales:** {self._format_number(raw_data.get('price_to_sales'))}")

        md.append("\n## Financial Health")
        md.append(f"\n- **Profit Margin:** {self._format_percent(raw_data.get('profit_margin'))}")
        md.append(
            f"- **Operating Margin:** {self._format_percent(raw_data.get('operating_margin'))}"
        )
        md.append(f"- **ROE:** {self._format_percent(raw_data.get('roe'))}")
        md.append(f"- **ROA:** {self._format_percent(raw_data.get('roa'))}")
        md.append(f"- **Debt/Equity:** {self._format_number(raw_data.get('debt_to_equity'))}")
        md.append(f"- **Current Ratio:** {self._format_number(raw_data.get('current_ratio'))}")
        md.append(f"- **Quick Ratio:** {self._format_number(raw_data.get('quick_ratio'))}")

        return md

    def _format_number(self, value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            if isinstance(value, (int, float)):
                if value > 1e9:
                    return f"${value/1e9:.2f}B"
                elif value > 1e6:
                    return f"${value/1e6:.2f}M"
                elif value > 1000:
                    return f"{value:,.2f}"
                else:
                    return f"{value:.2f}"
            return str(value)
        except:
            return "N/A"

    def _format_percent(self, value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            if isinstance(value, (int, float)):
                if value < 1:
                    return f"{value*100:.2f}%"
                else:
                    return f"{value:.2f}%"
            return str(value)
        except:
            return "N/A"


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

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        if not raw_data:
            return []

        md = []
        md.append("\n## Price Data Summary")
        md.append(
            f"\n- **Period:** {raw_data['date_range']['start']} to {raw_data['date_range']['end']}"
        )
        md.append(f"- **Data Points:** {raw_data['shape'][0]} days")
        md.append(f"\n### Latest Price ({raw_data['latest']['date']})")
        md.append(f"- **Close:** ${raw_data['latest']['close']:.2f}")
        md.append(f"- **Open:** ${raw_data['latest']['open']:.2f}")
        md.append(f"- **High:** ${raw_data['latest']['high']:.2f}")
        md.append(f"- **Low:** ${raw_data['latest']['low']:.2f}")
        md.append(f"- **Volume:** {raw_data['latest']['volume']:,}")
        md.append(f"\n### Statistics")
        md.append(f"- **52W High:** ${raw_data['statistics']['high_52w']:.2f}")
        md.append(f"- **52W Low:** ${raw_data['statistics']['low_52w']:.2f}")
        md.append(f"- **Avg Volume:** {raw_data['statistics']['avg_volume']:,.0f}")
        md.append(f"- **Volatility (std):** {raw_data['statistics']['volatility']:.4f}")

        return md


class FundamentalsSection(ReportSection):
    """Fundamentals section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching fundamentals for {ticker}")
        fundamentals = fetcher.fetch_fundamentals(ticker, use_cache=use_cache)
        return {k: {"shape": v.shape, "has_data": not v.empty} for k, v in fundamentals.items()}

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Fundamental Data Availability")
        for key, val in raw_data.items():
            status = "✓ Available" if val["has_data"] else "✗ Not Available"
            shape_str = f"({val['shape'][0]}x{val['shape'][1]})" if val["has_data"] else ""
            md.append(f"- **{key.replace('_', ' ').title()}:** {status} {shape_str}")
        return md


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

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Earnings")
        md.append(f"\n- **Historical Earnings:** {raw_data['history_count']} records")
        md.append(f"- **Earnings Dates:** {raw_data['dates_count']} dates")

        if raw_data["latest_earnings"]:
            md.append("\n### Recent Earnings History")
            md.append("\n| Quarter | EPS Actual | EPS Estimate | Difference | Surprise % |")
            md.append("|---------|-----------|--------------|------------|-----------|")
            for e in raw_data["latest_earnings"]:
                md.append(
                    f"| {e.get('quarter', 'N/A')} | {e.get('epsActual', 'N/A')} | {e.get('epsEstimate', 'N/A')} | {e.get('epsDifference', 'N/A')} | {self._format_percent(e.get('surprisePercent'))} |"
                )

        return md

    def _format_percent(self, value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            if isinstance(value, (int, float)):
                if value < 1:
                    return f"{value*100:.2f}%"
                else:
                    return f"{value:.2f}%"
            return str(value)
        except:
            return "N/A"


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

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Institutional Ownership")
        md.append(f"\n- **Institutional Holders:** {raw_data['institutional_count']}")
        md.append(f"- **Mutual Fund Holders:** {raw_data['mutualfund_count']}")

        if raw_data["top_institutional"]:
            md.append("\n### Top Institutional Holders")
            md.append("\n| Holder | % Held | Shares | Value |")
            md.append("|--------|--------|--------|-------|")
            for h in raw_data["top_institutional"]:
                pct = self._format_percent(h.get("pctHeld"))
                shares = f"{h.get('Shares', 0):,}" if h.get("Shares") else "N/A"
                value = f"${h.get('Value', 0):,}" if h.get("Value") else "N/A"
                holder_name = str(h.get("Holder", "N/A"))[:50]
                md.append(f"| {holder_name} | {pct} | {shares} | {value} |")

        return md

    def _format_percent(self, value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            if isinstance(value, (int, float)):
                if value < 1:
                    return f"{value*100:.2f}%"
                else:
                    return f"{value:.2f}%"
            return str(value)
        except:
            return "N/A"


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

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Dividends & Stock Splits")
        md.append(f"\n- **Total Dividend Payments:** {raw_data['dividend_count']}")
        md.append(f"- **Stock Splits:** {raw_data['split_count']}")

        if raw_data["recent_dividends"]:
            md.append("\n### Recent Dividends (Last 10)")
            md.append("\n| Date | Amount |")
            md.append("|------|--------|")
            for d in raw_data["recent_dividends"]:
                date = d.get("Date", "N/A")
                amount = f"${d.get('Dividends', 0):.4f}" if d.get("Dividends") else "N/A"
                md.append(f"| {date} | {amount} |")

        if raw_data["recent_splits"]:
            md.append("\n### Stock Splits")
            md.append("\n| Date | Split Ratio |")
            md.append("|------|-------------|")
            for s in raw_data["recent_splits"]:
                date = s.get("Date", "N/A")
                ratio = s.get("Stock Splits", "N/A")
                md.append(f"| {date} | {ratio} |")

        return md


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

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Analyst Ratings")
        md.append(f"\n- **Total Recommendations:** {raw_data['recommendation_count']}")
        md.append(f"- **Upgrades/Downgrades:** {raw_data['upgrade_downgrade_count']}")

        if raw_data["recent_recommendations"]:
            md.append("\n### Recommendation Summary")
            md.append("\n| Period | Strong Buy | Buy | Hold | Sell | Strong Sell |")
            md.append("|--------|-----------|-----|------|------|-------------|")
            for r in raw_data["recent_recommendations"][:10]:
                period = r.get("period", "N/A")
                strong_buy = r.get("strongBuy", 0)
                buy = r.get("buy", 0)
                hold = r.get("hold", 0)
                sell = r.get("sell", 0)
                strong_sell = r.get("strongSell", 0)
                md.append(f"| {period} | {strong_buy} | {buy} | {hold} | {sell} | {strong_sell} |")

        if raw_data["recent_changes"]:
            md.append("\n### Recent Upgrades/Downgrades")
            md.append("\n| Firm | Action | From | To | Price Target |")
            md.append("|------|--------|------|----|--------------| ")
            for r in raw_data["recent_changes"][:10]:
                firm = str(r.get("Firm", "N/A"))[:30]
                action = r.get("Action", "N/A")
                from_grade = r.get("FromGrade", "-")
                to_grade = r.get("ToGrade", "N/A")
                price_target = r.get("currentPriceTarget", "N/A")
                if price_target != "N/A" and price_target is not None:
                    price_target = f"${price_target}"
                md.append(f"| {firm} | {action} | {from_grade} | {to_grade} | {price_target} |")

        return md


class NewsSection(ReportSection):
    """News section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Dict[str, Any]:
        logger.info(f"Fetching news for {ticker}")
        news = fetcher.fetch_news(ticker, use_cache=False)  # Always fresh
        return {"article_count": len(news), "recent_articles": news[:10] if news else []}

    def format_for_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data

    def format_for_markdown(self, raw_data: Dict[str, Any]) -> List[str]:
        md = []
        md.append("\n## Recent News")
        md.append(f"\n- **Articles Found:** {raw_data['article_count']}")

        if raw_data["recent_articles"]:
            md.append("\n### Headlines (Last 10)")
            for i, article in enumerate(raw_data["recent_articles"][:10], 1):
                content = article.get("content", {})
                title = content.get("title", "No title")
                provider = content.get("provider", {})
                publisher = provider.get("displayName", "Unknown")
                click_through = content.get("clickThroughUrl", {})
                link = click_through.get("url", "#")
                md.append(f"\n{i}. **{title}**")
                md.append(f"   - Publisher: {publisher}")
                md.append(f"   - [Read more]({link})")

        return md


class TechnicalAnalysisSection(ReportSection):
    """Technical analysis section"""

    def fetch_data(self, fetcher, ticker: str, use_cache: bool = True, **kwargs) -> Any:
        """Fetch price data and calculate technical indicators"""
        from .technical_analysis import TechnicalAnalyzer

        # Fetch 1 year of data for 200-day SMA calculation
        period = kwargs.get("period", "1y")
        price_data = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)

        # Calculate all indicators
        analyzer = TechnicalAnalyzer(price_data)
        analyzer.calculate_all_indicators()

        # Return analyzer instance for formatting
        return analyzer

    def format_for_json(self, raw_data: Any) -> Any:
        """Format technical analysis for JSON (return summary)"""
        if hasattr(raw_data, "get_summary"):
            return raw_data.get_summary()
        return None

    def format_for_markdown(self, raw_data: Any) -> List[str]:
        """Format technical analysis summary for main report"""
        md = []
        md.append("\n## Technical Analysis Summary")
        md.append("")

        if not hasattr(raw_data, "get_latest_values"):
            md.append("*Technical analysis not available*")
            return md

        # Get summary data
        latest = raw_data.get_latest_values()
        signals = raw_data.generate_signals()

        # Current price
        md.append(f"**Current Price:** ${latest['close_price']:.2f}")
        md.append(f"**As of:** {latest['date']}")
        md.append("")

        # Key signals
        if signals:
            md.append("### Key Signals")
            md.append("")
            for indicator, signal in signals.items():
                md.append(f"- **{indicator}:** {signal}")
            md.append("")

        # Key indicators table
        md.append("### Key Indicators")
        md.append("")
        md.append("| Indicator | Value |")
        md.append("|-----------|-------|")

        indicators = latest["indicators"]
        key_indicators = [
            ("SMA_20", "SMA (20)"),
            ("SMA_50", "SMA (50)"),
            ("RSI_14", "RSI (14)"),
            ("MACD", "MACD"),
            ("BB_upper", "Bollinger Upper"),
            ("BB_lower", "Bollinger Lower"),
        ]

        for key, label in key_indicators:
            if key in indicators and indicators[key] is not None:
                value = indicators[key]
                if "RSI" in key or "MACD" in key:
                    md.append(f"| {label} | {value:.2f} |")
                else:
                    md.append(f"| {label} | ${value:.2f} |")

        md.append("")
        md.append("*See technical_analysis.md for detailed analysis*")
        md.append("")

        return md


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

    def format_for_markdown(self, raw_data: Any) -> List[str]:
        """Format for Markdown - use analyzer's format_markdown()"""
        if hasattr(raw_data, "format_markdown"):
            return raw_data.format_markdown()
        return []
