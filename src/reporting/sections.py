"""
Report Section Handlers
Modular handlers for different data sections in reports
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import pandas as pd

from ..analysis.fundamental import FundamentalAnalyzer
from ..analysis.valuation import ValuationAnalyzer
from ..utils.report import format_number, format_percent, get_currency_symbol, safe_get

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
    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
        md = []
        md.append("\n## Company Information")
        md.append(f"\n- **Name:** {safe_get(raw_data, 'name')}")
        md.append(f"- **Sector:** {safe_get(raw_data, 'sector')}")
        md.append(f"- **Industry:** {safe_get(raw_data, 'industry')}")
        md.append(f"- **Exchange:** {safe_get(raw_data, 'exchange')}")
        md.append(f"- **Currency:** {safe_get(raw_data, 'currency')}")
        if raw_data.get("website") != "N/A":
            md.append(f"- **Website:** {raw_data.get('website')}")

        md.append("\n## Valuation Metrics")
        md.append(f"\n- **Market Cap:** {format_number(raw_data.get('market_cap'))}")
        md.append(
            f"- **P/E Ratio:** {safe_get(raw_data, 'pe_ratio', formatter=lambda x: f'{x:.2f}')}"
        )
        md.append(
            f"- **Forward P/E:** {safe_get(raw_data, 'forward_pe', formatter=lambda x: f'{x:.2f}')}"
        )
        md.append(
            f"- **PEG Ratio:** {safe_get(raw_data, 'peg_ratio', formatter=lambda x: f'{x:.2f}')}"
        )
        md.append(
            f"- **Price/Book:** {safe_get(raw_data, 'price_to_book', formatter=lambda x: f'{x:.2f}')}"
        )
        md.append(
            f"- **Price/Sales:** {safe_get(raw_data, 'price_to_sales', formatter=lambda x: f'{x:.2f}')}"
        )

        md.append("\n## Financial Health")
        md.append(f"\n- **Profit Margin:** {format_percent(raw_data.get('profit_margin'))}")
        md.append(f"- **Operating Margin:** {format_percent(raw_data.get('operating_margin'))}")
        md.append(f"- **ROE:** {format_percent(raw_data.get('roe'))}")
        md.append(f"- **ROA:** {format_percent(raw_data.get('roa'))}")
        md.append(
            f"- **Debt/Equity:** {safe_get(raw_data, 'debt_to_equity', formatter=lambda x: f'{x:.2f}')}"
        )
        md.append(
            f"- **Current Ratio:** {safe_get(raw_data, 'current_ratio', formatter=lambda x: f'{x:.2f}')}"
        )
        md.append(
            f"- **Quick Ratio:** {safe_get(raw_data, 'quick_ratio', formatter=lambda x: f'{x:.2f}')}"
        )

        return md


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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
        if not raw_data:
            return []

        symbol = get_currency_symbol(currency)
        md = []
        md.append("\n## Price Data Summary")
        md.append(
            f"\n- **Period:** {raw_data['date_range']['start']} to {raw_data['date_range']['end']}"
        )
        md.append(f"- **Data Points:** {raw_data['shape'][0]} days")
        md.append(f"\n### Latest Price ({raw_data['latest']['date']})")
        md.append(f"- **Close:** {symbol}{raw_data['latest']['close']:.2f}")
        md.append(f"- **Open:** {symbol}{raw_data['latest']['open']:.2f}")
        md.append(f"- **High:** {symbol}{raw_data['latest']['high']:.2f}")
        md.append(f"- **Low:** {symbol}{raw_data['latest']['low']:.2f}")
        md.append(f"- **Volume:** {raw_data['latest']['volume']:,}")
        md.append(f"\n### Statistics")
        md.append(f"- **52W High:** {symbol}{raw_data['statistics']['high_52w']:.2f}")
        md.append(f"- **52W Low:** {symbol}{raw_data['statistics']['low_52w']:.2f}")
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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
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
                    f"| {e.get('quarter', 'N/A')} | {e.get('epsActual', 'N/A')} | {e.get('epsEstimate', 'N/A')} | {e.get('epsDifference', 'N/A')} | {format_percent(e.get('surprisePercent'))} |"
                )

        return md


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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
        md = []
        md.append("\n## Institutional Ownership")
        md.append(f"\n- **Institutional Holders:** {raw_data['institutional_count']}")
        md.append(f"- **Mutual Fund Holders:** {raw_data['mutualfund_count']}")
        
        symbol = get_currency_symbol(currency)

        if raw_data["top_institutional"]:
            md.append("\n### Top Institutional Holders")
            md.append("\n| Holder | % Held | Shares | Value |")
            md.append("|--------|--------|--------|-------|")
            for h in raw_data["top_institutional"]:
                pct = format_percent(h.get("pctHeld"))
                shares = f"{h.get('Shares', 0):,}" if h.get("Shares") else "N/A"
                value = f"{symbol}{h.get('Value', 0):,}" if h.get("Value") else "N/A"
                holder_name = str(h.get("Holder", "N/A"))[:50]
                md.append(f"| {holder_name} | {pct} | {shares} | {value} |")

        return md


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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
        md = []
        md.append("\n## Dividends & Stock Splits")
        md.append(f"\n- **Total Dividend Payments:** {raw_data['dividend_count']}")
        md.append(f"- **Stock Splits:** {raw_data['split_count']}")
        
        # Use currency parameter
        symbol = get_currency_symbol(currency)

        if raw_data["recent_dividends"]:
            md.append("\n### Recent Dividends (Last 10)")
            md.append("\n| Date | Amount |")
            md.append("|------|--------|")
            for d in raw_data["recent_dividends"]:
                date = d.get("Date", "N/A")
                amount = f"{symbol}{d.get('Dividends', 0):.4f}" if d.get("Dividends") else "N/A"
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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
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
                    symbol = get_currency_symbol(currency)
                    price_target = f"{symbol}{price_target}"
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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
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

    def format_for_markdown(self, raw_data: Any, currency: str = "USD") -> List[str]:
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
        
        symbol = get_currency_symbol(currency)

        # Current price
        md.append(f"**Current Price:** {symbol}{latest['close_price']:.2f}")
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
                    md.append(f"| {label} | {symbol}{value:.2f} |")

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

    def format_for_markdown(self, raw_data: Any, currency: str = "USD") -> List[str]:
        """Format for Markdown - use analyzer's format_markdown()"""
        if hasattr(raw_data, "format_markdown"):
            return raw_data.format_markdown()
        return []


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

        price_data = kwargs.get("price_data")
        if price_data is None or price_data.empty:
            period = kwargs.get("period", "1y")
            price_data = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)

        # Fetch benchmark data once (cache-aware)
        config = get_config()
        benchmark_ticker = config.benchmark_ticker
        benchmark_data = kwargs.get("benchmark_data")
        if not isinstance(benchmark_data, pd.DataFrame) or benchmark_data.empty:
            # Get date range from stock price data
            start_date = price_data.index.min()
            end_date = price_data.index.max()
            benchmark_data = fetcher.fetch_ticker(
                benchmark_ticker,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                use_cache=use_cache,
            )

        # Calculate all metrics (pass benchmark to avoid re-fetch)
        risk_analyzer = RiskMetrics()
        metrics = risk_analyzer.calculate_all_metrics(price_data, benchmark_data=benchmark_data)

        # Return tuple: (analyzer, metrics, benchmark) for dual formatting
        return (risk_analyzer, metrics, benchmark_data)

    def format_for_json(self, raw_data: Any) -> Any:
        """Format risk metrics for JSON"""
        if isinstance(raw_data, tuple) and len(raw_data) >= 2:
            _, metrics, _ = raw_data
            return metrics
        return None

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
        """Format risk analysis summary for main report"""
        md = []
        md.append("\n## Risk Analysis Summary")
        md.append("")

        if not isinstance(raw_data, tuple) or len(raw_data) < 2:
            md.append("*Risk analysis not available*")
            return md

        _, metrics, _ = raw_data

        # Performance overview
        if "returns" in metrics and metrics["returns"]:
            returns = metrics["returns"]
            md.append("### Performance")
            md.append("")
            md.append(f"**Cumulative Return:** {returns.get('cumulative_return', 0):.2%}")
            md.append(f"**Annualized Return:** {returns.get('annualized_return', 0):.2%}")
            md.append(f"**Win Rate:** {returns.get('win_rate', 0):.2%}")
            md.append("")

        # Risk metrics
        if "volatility" in metrics and metrics["volatility"]:
            vol = metrics["volatility"]
            sharpe = metrics.get("sharpe_ratio", 0)
            sortino = metrics.get("sortino_ratio", 0)
            information = metrics.get("information_ratio", 0)
            calmar = metrics.get("calmar_ratio", 0)

            md.append("### Risk Metrics")
            md.append("")
            md.append(f"**Annualized Volatility:** {vol.get('annualized_volatility', 0):.2%}")
            md.append(f"**Sharpe Ratio:** {sharpe:.2f}")
            md.append(f"**Sortino Ratio:** {sortino:.2f}")
            md.append(f"**Information Ratio:** {information:.2f}")
            md.append(f"**Calmar Ratio:** {calmar:.2f}")
            md.append("")

        # Drawdown
        if "drawdown" in metrics and metrics["drawdown"]:
            dd = metrics["drawdown"]
            md.append("### Drawdown")
            md.append("")
            md.append(f"**Maximum Drawdown:** {dd.get('max_drawdown', 0):.2%}")
            md.append(f"**Current Drawdown:** {dd.get('current_drawdown', 0):.2%}")
            md.append("")

        # Market risk
        if "market_risk" in metrics and metrics["market_risk"]:
            mr = metrics["market_risk"]
            md.append("### Market Risk")
            md.append("")
            md.append(f"**Beta:** {mr.get('beta', 0):.2f}")
            md.append(f"**Alpha:** {mr.get('alpha', 0):.2%}")
            md.append(f"**Correlation:** {mr.get('correlation', 0):.2f}")
            md.append("")

        md.append("*See risk_analysis.md for detailed risk metrics*")
        md.append("")

        return md


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

    def format_for_markdown(self, raw_data: Dict[str, Any], currency: str = "USD") -> List[str]:
        """Format valuation analysis as markdown"""
        md = ["## Valuation Analysis", ""]

        # DCF Valuation
        dcf = raw_data.get("dcf_valuation", {})
        md.append("### DCF (Discounted Cash Flow) Valuation")
        md.append("")
        
        symbol = get_currency_symbol(currency)

        if dcf.get("error"):
            md.append(f"⚠️ {dcf['error']}")
        elif dcf.get("intrinsic_value_per_share"):
            intrinsic = dcf["intrinsic_value_per_share"]
            current = dcf.get("current_price")
            discount = dcf.get("discount_premium_pct", 0)

            md.append(f"**Intrinsic Value:** {symbol}{intrinsic:.2f}")
            md.append(f"**Current Price:** {symbol}{current:.2f}")

            if discount < 0:
                md.append(
                    f"**Valuation:** 🔻 Undervalued by {abs(discount):.1f}% (trading below fair value)"
                )
            elif discount > 0:
                md.append(
                    f"**Valuation:** 🔺 Overvalued by {discount:.1f}% (trading above fair value)"
                )
            else:
                md.append("**Valuation:** Fairly valued")

            md.append("")
            md.append("**Assumptions:**")
            md.append(f"- FCF Growth Rate: {dcf.get('growth_rate_used', 0):.1f}%")
            md.append(f"- Terminal Growth: {dcf.get('terminal_growth_rate', 0):.1f}%")
            md.append(f"- WACC: {dcf.get('wacc_used', 0):.1f}%")
            md.append(f"- Current FCF: {symbol}{format_number(dcf.get('fcf_current', 0), currency)}")

        md.append("")

        # DDM Valuation
        ddm = raw_data.get("ddm_valuation", {})
        md.append("### DDM (Dividend Discount Model) Valuation")
        md.append("")
        
        symbol = get_currency_symbol(currency)

        if ddm.get("error"):
            md.append(f"⚠️ {ddm['error']}")
        elif ddm.get("intrinsic_value_per_share"):
            intrinsic = ddm["intrinsic_value_per_share"]
            current = ddm.get("current_price")
            discount = ddm.get("discount_premium_pct", 0)

            md.append(f"**Intrinsic Value:** {symbol}{intrinsic:.2f}")
            md.append(f"**Current Price:** {symbol}{current:.2f}")

            if discount < 0:
                md.append(
                    f"**Valuation:** 🔻 Undervalued by {abs(discount):.1f}% (dividend investor opportunity)"
                )
            elif discount > 0:
                md.append(f"**Valuation:** 🔺 Overvalued by {discount:.1f}%")

            md.append("")
            md.append("**Assumptions:**")
            symbol = get_currency_symbol(currency)
            md.append(f"- Current Dividend: {symbol}{ddm.get('current_dividend', 0):.2f}")
            md.append(f"- Next Dividend Est.: {symbol}{ddm.get('next_dividend_estimate', 0):.2f}")
            md.append(f"- Dividend Growth: {ddm.get('growth_rate_used', 0):.1f}%")
            md.append(f"- Required Return: {ddm.get('required_return_used', 0):.1f}%")

        md.append("")

        # Dividend Analysis
        div = raw_data.get("dividend_analysis", {})
        md.append("### Dividend Analysis")
        md.append("")

        if not div.get("pays_dividends"):
            md.append("❌ Company does not pay dividends")
        else:
            yield_pct = div.get("dividend_yield", 0)
            annual_div = div.get("annual_dividend", 0)
            payout = div.get("payout_ratio", 0)
            growth = div.get("dividend_growth_rate")
            coverage = div.get("dividend_coverage_ratio")
            consecutive = div.get("consecutive_years", 0)
            score = div.get("sustainability_score", 0)
            rating = div.get("sustainability_rating", "Unknown")

            symbol = get_currency_symbol(currency)
            md.append(f"**Dividend Yield:** {yield_pct:.2f}%")
            md.append(f"**Annual Dividend:** {symbol}{annual_div:.2f}")
            md.append(f"**Payout Ratio:** {payout:.1f}%")

            if coverage:
                md.append(f"**Dividend Coverage:** {coverage:.2f}x")

            if growth:
                md.append(f"**Dividend Growth Rate:** {growth:.1f}%")

            md.append(f"**Consecutive Years:** {consecutive}")
            md.append("")
            md.append(f"**Sustainability Score:** {score}/100 ({rating})")

            warnings = div.get("warnings", [])
            if warnings:
                md.append("")
                md.append("**⚠️ Warnings:**")
                for warning in warnings:
                    md.append(f"- {warning}")

        md.append("")

        # Earnings Analysis
        earn = raw_data.get("earnings_analysis", {})
        md.append("### Earnings Analysis")
        md.append("")

        current_eps = earn.get("current_eps")
        forward_eps = earn.get("forward_eps")
        growth_1y = earn.get("eps_growth_1y")
        growth_3y = earn.get("eps_growth_3y_cagr")
        next_date = earn.get("next_earnings_date")
        next_est = earn.get("next_earnings_estimate")
        trend = earn.get("trend")

        symbol = get_currency_symbol(currency)
        if current_eps:
            md.append(f"**Current EPS (TTM):** {symbol}{current_eps:.2f}")
        if forward_eps:
            md.append(f"**Forward EPS:** {symbol}{forward_eps:.2f}")

        if growth_1y is not None:
            md.append(f"**EPS Growth (1Y):** {growth_1y:+.1f}%")
        if growth_3y is not None:
            md.append(f"**EPS Growth (3Y CAGR):** {growth_3y:+.1f}%")

        if trend:
            md.append(f"**Trend:** {trend}")

        if next_date:
            md.append("")
            md.append(f"**Next Earnings:** {next_date}")
            if next_est:
                md.append(f"**Estimate:** {symbol}{next_est:.2f}")

        # Recent surprises
        surprises = earn.get("recent_surprises", [])
        if surprises:
            md.append("")
            md.append("**Recent Earnings Surprises:**")
            md.append("")
            md.append("| Quarter | Actual | Estimate | Surprise % |")
            md.append("|---------|--------|----------|------------|")
            for s in surprises[-4:]:  # Last 4 quarters
                quarter = s.get("quarter", "")[:10]  # Truncate date
                actual = s.get("eps_actual", 0)
                estimate = s.get("eps_estimate", 0)
                surprise = s.get("surprise_pct", 0)
                md.append(f"| {quarter} | {symbol}{actual:.2f} | {symbol}{estimate:.2f} | {surprise:+.1f}% |")

        # Surprise statistics
        stats = earn.get("surprise_stats", {})
        if stats:
            beat_rate = stats.get("beat_rate", 0)
            avg_surprise = stats.get("avg_surprise_pct", 0)
            md.append("")
            md.append(
                f"**Beat Rate:** {beat_rate:.0f}% ({stats.get('positive_surprises', 0)}/{len(surprises)} quarters)"
            )
            md.append(f"**Avg Surprise:** {avg_surprise:+.1f}%")

        # Earnings quality
        quality = earn.get("earnings_quality", {})
        if quality.get("assessment"):
            md.append("")
            md.append("**Earnings Quality:**")
            md.append(f"- {quality['assessment']}")
            metrics = quality.get("metrics", {})
            if "cash_flow_to_earnings_ratio" in metrics:
                md.append(f"- CF/NI Ratio: {metrics['cash_flow_to_earnings_ratio']:.2f}x")

        md.append("")
        return md
