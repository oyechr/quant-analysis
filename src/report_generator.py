"""
Report Generator Module
Aggregates and formats data from DataFetcher into comprehensive reports
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import logging

from .data_fetcher import DataFetcher

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates comprehensive reports from financial data"""
    
    def __init__(self, data_fetcher: Optional[DataFetcher] = None, output_dir: str = "data"):
        """
        Initialize ReportGenerator
        
        Args:
            data_fetcher: DataFetcher instance 
            output_dir: Directory to save reports
        """
        self.fetcher = data_fetcher or DataFetcher()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def generate_full_report(
        self,
        ticker: str,
        period: str = "1mo",
        output_format: str = "both",
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Generate comprehensive report with all available data
        
        Args:
            ticker: Stock ticker symbol
            period: Period for price data (1mo, 3mo, 6mo, 1y, 2y, 5y, etc.)
            output_format: "json", "markdown", or "both"
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with all fetched data and metadata
        """
        ticker = ticker.upper()
        logger.info(f"Generating full report for {ticker}")
        
        # Fetch all data
        report_data: Dict[str, Any] = {
            'ticker': ticker,
            'generated_at': datetime.now().isoformat(),
            'period': period,
        }
        
        # 1. Basic info
        logger.info(f"Fetching info for {ticker}")
        report_data['info'] = self.fetcher.get_ticker_info(ticker, use_cache=use_cache)
        
        # 2. Price data
        logger.info(f"Fetching price data for {ticker}")
        try:
            price_data = self.fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)
            report_data['price_data'] = {
                'shape': price_data.shape,
                'date_range': {
                    'start': str(price_data.index[0]),
                    'end': str(price_data.index[-1])
                },
                'latest': {
                    'date': str(price_data.index[-1]),
                    'open': float(price_data['Open'].iloc[-1]),
                    'high': float(price_data['High'].iloc[-1]),
                    'low': float(price_data['Low'].iloc[-1]),
                    'close': float(price_data['Close'].iloc[-1]),
                    'volume': int(price_data['Volume'].iloc[-1])
                },
                'statistics': {
                    'high_52w': float(price_data['High'].max()),
                    'low_52w': float(price_data['Low'].min()),
                    'avg_volume': float(price_data['Volume'].mean()),
                    'volatility': float(price_data['Close'].pct_change().std())
                }
            }
        except Exception as e:
            logger.warning(f"Could not fetch price data: {e}")
            report_data['price_data'] = None
        
        # 3. Fundamentals
        logger.info(f"Fetching fundamentals for {ticker}")
        fundamentals = self.fetcher.fetch_fundamentals(ticker, use_cache=use_cache)
        report_data['fundamentals'] = {
            k: {'shape': v.shape, 'has_data': not v.empty}
            for k, v in fundamentals.items()
        }
        
        # 4. Earnings
        logger.info(f"Fetching earnings for {ticker}")
        earnings = self.fetcher.fetch_earnings(ticker, use_cache=use_cache)
        report_data['earnings'] = {
            'history_count': len(earnings['earnings_history']),
            'dates_count': len(earnings['earnings_dates']),
            'latest_earnings': earnings['earnings_history'].head(3).reset_index().replace({float('nan'): None}).to_dict('records') if not earnings['earnings_history'].empty else [],
            'upcoming_dates': earnings['earnings_dates'].head(3).reset_index().replace({float('nan'): None}).to_dict('records') if not earnings['earnings_dates'].empty else []
        }
        
        # 5. Institutional holders
        logger.info(f"Fetching holders for {ticker}")
        holders = self.fetcher.fetch_institutional_holders(ticker, use_cache=use_cache)
        report_data['holders'] = {
            'institutional_count': len(holders['institutional_holders']),
            'mutualfund_count': len(holders['mutualfund_holders']),
            'top_institutional': holders['institutional_holders'].head(5).replace({float('nan'): None}).to_dict('records') if not holders['institutional_holders'].empty else [],
            'top_mutualfund': holders['mutualfund_holders'].head(5).replace({float('nan'): None}).to_dict('records') if not holders['mutualfund_holders'].empty else []
        }
        
        # 6. Dividends
        logger.info(f"Fetching dividends for {ticker}")
        dividends = self.fetcher.fetch_dividends(ticker, use_cache=use_cache)
        report_data['dividends'] = {
            'dividend_count': len(dividends['dividends']),
            'split_count': len(dividends['splits']),
            'recent_dividends': dividends['dividends'].tail(10).reset_index().replace({float('nan'): None}).to_dict('records') if not dividends['dividends'].empty else [],
            'recent_splits': dividends['splits'].tail(5).reset_index().replace({float('nan'): None}).to_dict('records') if not dividends['splits'].empty else []
        }
        
        # 7. Analyst Ratings
        logger.info(f"Fetching analyst ratings for {ticker}")
        analyst = self.fetcher.fetch_analyst_ratings(ticker, use_cache=use_cache)
        report_data['analyst_ratings'] = {
            'recommendation_count': len(analyst['recommendations']),
            'upgrade_downgrade_count': len(analyst['upgrades_downgrades']),
            'recent_recommendations': analyst['recommendations'].head(10).replace({float('nan'): None}).to_dict('records') if not analyst['recommendations'].empty else [],
            'recent_changes': analyst['upgrades_downgrades'].head(10).replace({float('nan'): None}).to_dict('records') if not analyst['upgrades_downgrades'].empty else []
        }
        
        # 8. News
        logger.info(f"Fetching news for {ticker}")
        news = self.fetcher.fetch_news(ticker, use_cache=False)  # Always fresh news
        report_data['news'] = {
            'article_count': len(news),
            'recent_articles': news[:10] if news else []  # Top 10 most recent
        }
        
        # Save outputs
        if output_format in ["json", "both"]:
            self._save_json_report(ticker, report_data)
        
        if output_format in ["markdown", "both"]:
            self._save_markdown_report(ticker, report_data)
        
        logger.info(f"Report generation complete for {ticker}")
        return report_data
    
    def _save_json_report(self, ticker: str, data: Dict[str, Any]):
        """Save report as JSON"""
        ticker_dir = self.output_dir / ticker
        ticker_dir.mkdir(exist_ok=True)
        output_file = ticker_dir / "full_report.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"JSON report saved: {output_file}")
    
    def _save_markdown_report(self, ticker: str, data: Dict[str, Any]):
        """Save report as Markdown"""
        ticker_dir = self.output_dir / ticker
        ticker_dir.mkdir(exist_ok=True)
        output_file = ticker_dir / "report.md"
        
        md = []
        md.append(f"# {ticker} - Comprehensive Stock Report")
        md.append(f"\n**Generated:** {data['generated_at']}")
        md.append(f"\n**Period:** {data['period']}")
        
        # Basic Info
        info = data['info']
        md.append("\n## Company Information")
        md.append(f"\n- **Name:** {info.get('name', 'N/A')}")
        md.append(f"- **Sector:** {info.get('sector', 'N/A')}")
        md.append(f"- **Industry:** {info.get('industry', 'N/A')}")
        md.append(f"- **Exchange:** {info.get('exchange', 'N/A')}")
        md.append(f"- **Currency:** {info.get('currency', 'N/A')}")
        if info.get('website') != 'N/A':
            md.append(f"- **Website:** {info.get('website')}")
        
        # Valuation Metrics
        md.append("\n## Valuation Metrics")
        md.append(f"\n- **Market Cap:** {self._format_number(info.get('market_cap'))}")
        md.append(f"- **P/E Ratio:** {self._format_number(info.get('pe_ratio'))}")
        md.append(f"- **Forward P/E:** {self._format_number(info.get('forward_pe'))}")
        md.append(f"- **PEG Ratio:** {self._format_number(info.get('peg_ratio'))}")
        md.append(f"- **Price/Book:** {self._format_number(info.get('price_to_book'))}")
        md.append(f"- **Price/Sales:** {self._format_number(info.get('price_to_sales'))}")
        
        # Financial Health
        md.append("\n## Financial Health")
        md.append(f"\n- **Profit Margin:** {self._format_percent(info.get('profit_margin'))}")
        md.append(f"- **Operating Margin:** {self._format_percent(info.get('operating_margin'))}")
        md.append(f"- **ROE:** {self._format_percent(info.get('roe'))}")
        md.append(f"- **ROA:** {self._format_percent(info.get('roa'))}")
        md.append(f"- **Debt/Equity:** {self._format_number(info.get('debt_to_equity'))}")
        md.append(f"- **Current Ratio:** {self._format_number(info.get('current_ratio'))}")
        md.append(f"- **Quick Ratio:** {self._format_number(info.get('quick_ratio'))}")
        
        # Price Data
        if data['price_data']:
            price = data['price_data']
            md.append("\n## Price Data Summary")
            md.append(f"\n- **Period:** {price['date_range']['start']} to {price['date_range']['end']}")
            md.append(f"- **Data Points:** {price['shape'][0]} days")
            md.append(f"\n### Latest Price ({price['latest']['date']})")
            md.append(f"- **Close:** ${price['latest']['close']:.2f}")
            md.append(f"- **Open:** ${price['latest']['open']:.2f}")
            md.append(f"- **High:** ${price['latest']['high']:.2f}")
            md.append(f"- **Low:** ${price['latest']['low']:.2f}")
            md.append(f"- **Volume:** {price['latest']['volume']:,}")
            md.append(f"\n### Statistics")
            md.append(f"- **52W High:** ${price['statistics']['high_52w']:.2f}")
            md.append(f"- **52W Low:** ${price['statistics']['low_52w']:.2f}")
            md.append(f"- **Avg Volume:** {price['statistics']['avg_volume']:,.0f}")
            md.append(f"- **Volatility (std):** {price['statistics']['volatility']:.4f}")
        
        # Fundamentals
        md.append("\n## Fundamental Data Availability")
        for key, val in data['fundamentals'].items():
            status = "✓ Available" if val['has_data'] else "✗ Not Available"
            shape_str = f"({val['shape'][0]}x{val['shape'][1]})" if val['has_data'] else ""
            md.append(f"- **{key.replace('_', ' ').title()}:** {status} {shape_str}")
        
        # Earnings
        earnings = data['earnings']
        md.append("\n## Earnings")
        md.append(f"\n- **Historical Earnings:** {earnings['history_count']} records")
        md.append(f"- **Earnings Dates:** {earnings['dates_count']} dates")
        
        if earnings['latest_earnings']:
            md.append("\n### Recent Earnings History")
            md.append("\n| Quarter | EPS Actual | EPS Estimate | Difference | Surprise % |")
            md.append("|---------|-----------|--------------|------------|-----------|")
            for e in earnings['latest_earnings']:
                md.append(f"| {e.get('quarter', 'N/A')} | {e.get('epsActual', 'N/A')} | {e.get('epsEstimate', 'N/A')} | {e.get('epsDifference', 'N/A')} | {self._format_percent(e.get('surprisePercent'))} |")
        
        # Holders
        holders = data['holders']
        md.append("\n## Institutional Ownership")
        md.append(f"\n- **Institutional Holders:** {holders['institutional_count']}")
        md.append(f"- **Mutual Fund Holders:** {holders['mutualfund_count']}")
        
        if holders['top_institutional']:
            md.append("\n### Top Institutional Holders")
            md.append("\n| Holder | % Held | Shares | Value |")
            md.append("|--------|--------|--------|-------|")
            for h in holders['top_institutional']:
                pct = self._format_percent(h.get('pctHeld'))
                shares = f"{h.get('Shares', 0):,}" if h.get('Shares') else 'N/A'
                value = f"${h.get('Value', 0):,}" if h.get('Value') else 'N/A'
                holder_name = str(h.get('Holder', 'N/A'))[:50]  # Truncate long names
                md.append(f"| {holder_name} | {pct} | {shares} | {value} |")
        
        # Dividends
        dividends = data['dividends']
        md.append("\n## Dividends & Stock Splits")
        md.append(f"\n- **Total Dividend Payments:** {dividends['dividend_count']}")
        md.append(f"- **Stock Splits:** {dividends['split_count']}")
        
        if dividends['recent_dividends']:
            md.append("\n### Recent Dividends (Last 10)")
            md.append("\n| Date | Amount |")
            md.append("|------|--------|")
            for d in dividends['recent_dividends']:
                date = d.get('Date', 'N/A')
                amount = f"${d.get('Dividends', 0):.4f}" if d.get('Dividends') else 'N/A'
                md.append(f"| {date} | {amount} |")
        
        if dividends['recent_splits']:
            md.append("\n### Stock Splits")
            md.append("\n| Date | Split Ratio |")
            md.append("|------|-------------|")
            for s in dividends['recent_splits']:
                date = s.get('Date', 'N/A')
                ratio = s.get('Stock Splits', 'N/A')
                md.append(f"| {date} | {ratio} |")
        
        # Analyst Ratings
        analyst = data['analyst_ratings']
        md.append("\n## Analyst Ratings")
        md.append(f"\n- **Total Recommendations:** {analyst['recommendation_count']}")
        md.append(f"- **Upgrades/Downgrades:** {analyst['upgrade_downgrade_count']}")
        
        # Show recommendation summary by period
        if analyst['recent_recommendations']:
            md.append("\n### Recommendation Summary")
            md.append("\n| Period | Strong Buy | Buy | Hold | Sell | Strong Sell |")
            md.append("|--------|-----------|-----|------|------|-------------|")
            for r in analyst['recent_recommendations'][:10]:
                period = r.get('period', 'N/A')
                strong_buy = r.get('strongBuy', 0)
                buy = r.get('buy', 0)
                hold = r.get('hold', 0)
                sell = r.get('sell', 0)
                strong_sell = r.get('strongSell', 0)
                md.append(f"| {period} | {strong_buy} | {buy} | {hold} | {sell} | {strong_sell} |")
        
        # Show recent upgrades/downgrades
        if analyst['recent_changes']:
            md.append("\n### Recent Upgrades/Downgrades")
            md.append("\n| Firm | Action | From | To | Price Target |")
            md.append("|------|--------|------|----|--------------| ")
            for r in analyst['recent_changes'][:10]:
                firm = str(r.get('Firm', 'N/A'))[:30]
                action = r.get('Action', 'N/A')
                from_grade = r.get('FromGrade', '-')
                to_grade = r.get('ToGrade', 'N/A')
                price_target = r.get('currentPriceTarget', 'N/A')
                if price_target != 'N/A' and price_target is not None:
                    price_target = f"${price_target}"
                md.append(f"| {firm} | {action} | {from_grade} | {to_grade} | {price_target} |")
        
        # News
        news = data['news']
        md.append("\n## Recent News")
        md.append(f"\n- **Articles Found:** {news['article_count']}")
        
        if news['recent_articles']:
            md.append("\n### Headlines (Last 10)")
            for i, article in enumerate(news['recent_articles'][:10], 1):
                # Access nested content structure
                content = article.get('content', {})
                title = content.get('title', 'No title')
                provider = content.get('provider', {})
                publisher = provider.get('displayName', 'Unknown')
                click_through = content.get('clickThroughUrl', {})
                link = click_through.get('url', '#')
                md.append(f"\n{i}. **{title}**")
                md.append(f"   - Publisher: {publisher}")
                md.append(f"   - [Read more]({link})")
        
        # Write file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        
        logger.info(f"Markdown report saved: {output_file}")
    
    def _format_number(self, value: Any) -> str:
        """Format number for display"""
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
        """Format percentage for display"""
        if value is None:
            return "N/A"
        try:
            if isinstance(value, (int, float)):
                return f"{value*100:.2f}%" if value < 1 else f"{value:.2f}%"
            return str(value)
        except:
            return "N/A"


# Convenience function
def generate_report(ticker: str, period: str = "1y", output_format: str = "both") -> Dict[str, Any]:
    """Quick report generation"""
    generator = ReportGenerator()
    return generator.generate_full_report(ticker, period=period, output_format=output_format)
