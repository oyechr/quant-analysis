"""
Report Generator Module
Aggregates and formats data from DataFetcher into comprehensive reports
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging

from .data_fetcher import DataFetcher
from .report_sections import (
    ReportSection,
    InfoSection,
    PriceDataSection,
    FundamentalsSection,
    EarningsSection,
    HoldersSection,
    DividendsSection,
    AnalystRatingsSection,
    NewsSection,
    TechnicalAnalysisSection,
    FundamentalAnalysisSection
)

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
        
        # Initialize all report sections
        self.sections: Dict[str, ReportSection] = {
            'info': InfoSection(),
            'price_data': PriceDataSection(),
            'fundamentals': FundamentalsSection(),
            'earnings': EarningsSection(),
            'holders': HoldersSection(),
            'dividends': DividendsSection(),
            'analyst_ratings': AnalystRatingsSection(),
            'news': NewsSection(),
        }
    
    def generate_full_report(
        self,
        ticker: str,
        period: str = "1y",
        output_format: str = "both",
        use_cache: bool = True,
        include_technical: bool = False,
        include_fundamental: bool = False
    ) -> Dict[str, Any]:
        """
        Generate comprehensive report with all available data
        
        Args:
            ticker: Stock ticker symbol
            period: Period for price data (1mo, 3mo, 6mo, 1y, 2y, 5y, etc.)
            output_format: "json", "markdown", or "both"
            use_cache: Whether to use cached data
            include_technical: Whether to include technical analysis (requires 1y period)
            include_fundamental: Whether to include fundamental analysis
            
        Returns:
            Dictionary with all fetched data and metadata
        """
        ticker = ticker.upper()
        logger.info(f"Generating full report for {ticker}")
        
        # Initialize report with metadata
        report_data: Dict[str, Any] = {
            'ticker': ticker,
            'generated_at': datetime.now().isoformat(),
            'period': period,
        }
        
        # Fetch data from all sections
        for section_name, section in self.sections.items():
            try:
                raw_data = section.fetch_data(
                    self.fetcher, 
                    ticker, 
                    use_cache=use_cache,
                    period=period  # Pass through for price data
                )
                report_data[section_name] = section.format_for_json(raw_data)
            except Exception as e:
                logger.error(f"Error processing {section_name} section: {e}")
                report_data[section_name] = None
        
        # Add technical analysis if requested
        technical_analyzer = None
        if include_technical:
            try:
                tech_section = TechnicalAnalysisSection()
                technical_analyzer = tech_section.fetch_data(
                    self.fetcher,
                    ticker,
                    use_cache=use_cache,
                    period='1y'  # Force 1y for technical analysis
                )
                report_data['technical_analysis'] = tech_section.format_for_json(technical_analyzer)
            except Exception as e:
                logger.error(f"Error processing technical analysis: {e}")
                report_data['technical_analysis'] = None
        
        # Add fundamental analysis if requested
        fundamental_analyzer = None
        if include_fundamental:
            try:
                fund_section = FundamentalAnalysisSection()
                # Pass price data if available for market-based calculations
                price_data = self.fetcher.fetch_ticker(ticker, period='1y', use_cache=use_cache)
                fundamental_analyzer = fund_section.fetch_data(
                    self.fetcher,
                    ticker,
                    use_cache=use_cache,
                    price_data=price_data
                )
                report_data['fundamental_analysis'] = fund_section.format_for_json(fundamental_analyzer)
            except Exception as e:
                logger.error(f"Error processing fundamental analysis: {e}")
                report_data['fundamental_analysis'] = None
        
        # Save outputs
        if output_format in ["json", "both"]:
            self._save_json_report(ticker, report_data)
        
        if output_format in ["markdown", "both"]:
            self._save_markdown_report(ticker, report_data, technical_analyzer, fundamental_analyzer)
        
        logger.info(f"Report generation complete for {ticker}")
        return report_data
    
    def _save_json_report(self, ticker: str, data: Dict[str, Any]):
        """Save report as JSON"""
        reports_dir = self.output_dir / ticker / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "full_report.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"JSON report saved: {output_file}")
    
    def _save_markdown_report(self, ticker: str, data: Dict[str, Any], technical_analyzer=None, fundamental_analyzer=None):
        """Save report as Markdown using section handlers"""
        reports_dir = self.output_dir / ticker / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "report.md"
        
        md = []
        md.append(f"# {ticker} - Comprehensive Stock Report")
        md.append(f"\n**Generated:** {data['generated_at']}")
        md.append(f"\n**Period:** {data['period']}")
        
        # Generate markdown for each section using handlers
        for section_name, section in self.sections.items():
            section_data = data.get(section_name)
            if section_data is not None:
                try:
                    # Each section handler formats its own markdown
                    md.extend(section.format_for_markdown(section_data))
                except Exception as e:
                    logger.warning(f"Error formatting markdown for {section_name}: {e}")
        
        # Add fundamental analysis summary if available
        if fundamental_analyzer and data.get('fundamental_analysis'):
            try:
                fund_section = FundamentalAnalysisSection()
                md.extend(fund_section.format_for_markdown(fundamental_analyzer))
            except Exception as e:
                logger.warning(f"Error formatting fundamental analysis markdown: {e}")
        
        # Add technical analysis summary if available
        if technical_analyzer and data.get('technical_analysis'):
            try:
                tech_section = TechnicalAnalysisSection()
                md.extend(tech_section.format_for_markdown(technical_analyzer))
            except Exception as e:
                logger.warning(f"Error formatting technical analysis markdown: {e}")
        
        # Write main report
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        
        logger.info(f"Markdown report saved: {output_file}")
        
        # Save detailed technical analysis markdown if available
        if technical_analyzer:
            self._save_technical_markdown(ticker, technical_analyzer)
            self._save_technical_json(ticker, technical_analyzer)
        
        # Save detailed fundamental analysis markdown if available
        if fundamental_analyzer:
            self._save_fundamental_markdown(ticker, fundamental_analyzer)
            self._save_fundamental_json(ticker, fundamental_analyzer)
    
    def _save_technical_json(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate JSON file"""
        reports_dir = self.output_dir / ticker / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "technical_analysis.json"
        
        # Get summary with all statistics, indicators, and signals
        technical_data = technical_analyzer.get_summary()
        
        # Write file
        with open(output_file, 'w') as f:
            json.dump(technical_data, f, indent=2, default=str)
        
        logger.info(f"Technical analysis JSON saved: {output_file}")
    
    def _save_technical_markdown(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate markdown file"""
        reports_dir = self.output_dir / ticker / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "technical_analysis.md"
        
        md = []
        md.append(f"# {ticker} - Technical Analysis Report")
        md.append("")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get detailed markdown from analyzer
        md.extend(technical_analyzer.format_markdown())
        
        # Write file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        
        logger.info(f"Technical analysis markdown saved: {output_file}")
    
    def _save_fundamental_json(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate JSON file"""
        reports_dir = self.output_dir / ticker / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "fundamental_analysis.json"
        
        # Get summary with all metrics
        fundamental_data = fundamental_analyzer.get_summary()
        
        # Write file
        with open(output_file, 'w') as f:
            json.dump(fundamental_data, f, indent=2, default=str)
        
        logger.info(f"Fundamental analysis JSON saved: {output_file}")
    
    def _save_fundamental_markdown(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate markdown file"""
        reports_dir = self.output_dir / ticker / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "fundamental_analysis.md"
        
        md = []
        md.append(f"# {ticker} - Fundamental Analysis Report")
        md.append("")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get detailed markdown from analyzer
        md.extend(fundamental_analyzer.format_markdown())
        
        # Write file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        
        logger.info(f"Fundamental analysis markdown saved: {output_file}")


# Convenience function
def generate_report(ticker: str, period: str = "1y", output_format: str = "both") -> Dict[str, Any]:
    """Quick report generation"""
    generator = ReportGenerator()
    return generator.generate_full_report(ticker, period=period, output_format=output_format)

