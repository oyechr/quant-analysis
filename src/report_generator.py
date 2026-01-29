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
    NewsSection
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
        """Save report as Markdown using section handlers"""
        ticker_dir = self.output_dir / ticker
        ticker_dir.mkdir(exist_ok=True)
        output_file = ticker_dir / "report.md"
        
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
        
        # Write file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        
        logger.info(f"Markdown report saved: {output_file}")


# Convenience function
def generate_report(ticker: str, period: str = "1y", output_format: str = "both") -> Dict[str, Any]:
    """Quick report generation"""
    generator = ReportGenerator()
    return generator.generate_full_report(ticker, period=period, output_format=output_format)

