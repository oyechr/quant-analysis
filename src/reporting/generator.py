"""
Report Generator Module
Aggregates and formats data from DataFetcher into comprehensive reports
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..data_fetcher import DataFetcher
from .sections import (
    AnalystRatingsSection,
    DividendsSection,
    EarningsSection,
    FundamentalAnalysisSection,
    FundamentalsSection,
    HoldersSection,
    InfoSection,
    NewsSection,
    PriceDataSection,
    ReportSection,
    RiskAnalysisSection,
    TechnicalAnalysisSection,
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
            "info": InfoSection(),
            "price_data": PriceDataSection(),
            "fundamentals": FundamentalsSection(),
            "earnings": EarningsSection(),
            "holders": HoldersSection(),
            "dividends": DividendsSection(),
            "analyst_ratings": AnalystRatingsSection(),
            "news": NewsSection(),
        }

    def generate_full_report(
        self,
        ticker: str,
        period: str = "1y",
        output_format: str = "both",
        use_cache: bool = True,
        include_technical: bool = False,
        include_fundamental: bool = False,
        include_risk: bool = False,
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
            include_risk: Whether to include risk metrics and performance analysis

        Returns:
            Dictionary with all fetched data and metadata
        """
        ticker = ticker.upper()
        logger.info(f"Generating full report for {ticker}")

        # Initialize report with metadata
        report_data: Dict[str, Any] = {
            "ticker": ticker,
            "generated_at": datetime.now().isoformat(),
            "period": period,
        }

        # Fetch data from all sections
        for section_name, section in self.sections.items():
            try:
                raw_data = section.fetch_data(
                    self.fetcher,
                    ticker,
                    use_cache=use_cache,
                    period=period,  # Pass through for price data
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
                    period="1y",  # Force 1y for technical analysis
                )
                report_data["technical_analysis"] = tech_section.format_for_json(technical_analyzer)
            except Exception as e:
                logger.error(f"Error processing technical analysis: {e}")
                report_data["technical_analysis"] = None

        # Add fundamental analysis if requested
        fundamental_analyzer = None
        if include_fundamental:
            try:
                fund_section = FundamentalAnalysisSection()
                # Pass price data if available for market-based calculations
                price_data = self.fetcher.fetch_ticker(ticker, period="1y", use_cache=use_cache)
                fundamental_analyzer = fund_section.fetch_data(
                    self.fetcher, ticker, use_cache=use_cache, price_data=price_data
                )
                report_data["fundamental_analysis"] = fund_section.format_for_json(
                    fundamental_analyzer
                )
            except Exception as e:
                logger.error(f"Error processing fundamental analysis: {e}")
                report_data["fundamental_analysis"] = None

        # Add risk analysis if requested
        risk_analyzer_tuple = None
        if include_risk:
            try:
                risk_section = RiskAnalysisSection()
                # Reuse price data from fundamental analysis if available
                price_data = self.fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)
                risk_analyzer_tuple = risk_section.fetch_data(
                    self.fetcher, ticker, use_cache=use_cache, price_data=price_data, period=period
                )
                report_data["risk_analysis"] = risk_section.format_for_json(risk_analyzer_tuple)
            except Exception as e:
                logger.error(f"Error processing risk analysis: {e}")
                report_data["risk_analysis"] = None

        # Save outputs
        if output_format in ["json", "both"]:
            self._save_json_report(ticker, report_data)

        if output_format in ["markdown", "both"]:
            self._save_markdown_report(
                ticker, report_data, technical_analyzer, fundamental_analyzer, risk_analyzer_tuple
            )

        logger.info(f"Report generation complete for {ticker}")
        return report_data

    def _save_json_report(self, ticker: str, data: Dict[str, Any]):
        """Save report as JSON"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "full_report.json"
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"JSON report saved: {output_file}")

    def _save_markdown_report(
        self, ticker: str, data: Dict[str, Any], technical_analyzer=None, fundamental_analyzer=None, risk_analyzer_tuple=None
    ):
        """Save report as Markdown using section handlers"""
        reports_dir = self.output_dir / ticker / "reports"
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
        if fundamental_analyzer and data.get("fundamental_analysis"):
            try:
                fund_section = FundamentalAnalysisSection()
                md.extend(fund_section.format_for_markdown(fundamental_analyzer))
            except Exception as e:
                logger.warning(f"Error formatting fundamental analysis markdown: {e}")

        # Add technical analysis summary if available
        if technical_analyzer and data.get("technical_analysis"):
            try:
                tech_section = TechnicalAnalysisSection()
                md.extend(tech_section.format_for_markdown(technical_analyzer))
            except Exception as e:
                logger.warning(f"Error formatting technical analysis markdown: {e}")

        # Add risk analysis summary if available
        if risk_analyzer_tuple and data.get("risk_analysis"):
            try:
                risk_section = RiskAnalysisSection()
                md.extend(risk_section.format_for_markdown(risk_analyzer_tuple))
            except Exception as e:
                logger.warning(f"Error formatting risk analysis markdown: {e}")

        # Write main report
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"Markdown report saved: {output_file}")

        # Save detailed technical analysis markdown if available
        if technical_analyzer:
            self._save_technical_markdown(ticker, technical_analyzer)
            self._save_technical_json(ticker, technical_analyzer)

        # Save detailed fundamental analysis markdown if available
        if fundamental_analyzer:
            self._save_fundamental_markdown(ticker, fundamental_analyzer)
            self._save_fundamental_json(ticker, fundamental_analyzer)

        # Save detailed risk analysis markdown if available
        if risk_analyzer_tuple:
            self._save_risk_markdown(ticker, risk_analyzer_tuple)
            self._save_risk_json(ticker, risk_analyzer_tuple)

    def _save_technical_json(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate JSON file"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "technical_analysis.json"

        # Get summary with all statistics, indicators, and signals
        technical_data = technical_analyzer.get_summary()

        # Write file
        with open(output_file, "w") as f:
            json.dump(technical_data, f, indent=2, default=str)

        logger.info(f"Technical analysis JSON saved: {output_file}")

    def _save_technical_markdown(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate markdown file"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "technical_analysis.md"

        md = []
        md.append(f"# {ticker} - Technical Analysis Report")
        md.append("")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Get detailed markdown from analyzer
        md.extend(technical_analyzer.format_markdown())

        # Write file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"Technical analysis markdown saved: {output_file}")

    def _save_fundamental_json(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate JSON file"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "fundamental_analysis.json"

        # Get summary with all metrics
        fundamental_data = fundamental_analyzer.get_summary()

        # Write file
        with open(output_file, "w") as f:
            json.dump(fundamental_data, f, indent=2, default=str)

        logger.info(f"Fundamental analysis JSON saved: {output_file}")

    def _save_fundamental_markdown(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate markdown file"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "fundamental_analysis.md"

        md = []
        md.append(f"# {ticker} - Fundamental Analysis Report")
        md.append("")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Get detailed markdown from analyzer
        md.extend(fundamental_analyzer.format_markdown())

        # Write file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"Fundamental analysis markdown saved: {output_file}")

    def _save_risk_json(self, ticker: str, risk_analyzer_tuple):
        """Save detailed risk analysis as separate JSON file"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "risk_analysis.json"

        if not isinstance(risk_analyzer_tuple, tuple) or len(risk_analyzer_tuple) < 2:
            logger.warning("Invalid risk analyzer data for JSON export")
            return

        _, metrics, _ = risk_analyzer_tuple

        # Write file
        with open(output_file, "w") as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info(f"Risk analysis JSON saved: {output_file}")

    def _save_risk_markdown(self, ticker: str, risk_analyzer_tuple):
        """Save detailed risk analysis as separate markdown file"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "risk_analysis.md"

        if not isinstance(risk_analyzer_tuple, tuple) or len(risk_analyzer_tuple) < 2:
            logger.warning("Invalid risk analyzer data for markdown export")
            return

        _, metrics, _ = risk_analyzer_tuple

        md = []
        md.append(f"# {ticker} - Risk Analysis Report")
        md.append("")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md.append("")

        # Returns Analysis
        md.append("## Returns Analysis")
        md.append("")
        if "returns" in metrics and metrics["returns"]:
            returns = metrics["returns"]
            md.append("### Daily Returns")
            md.append("")
            md.append(f"- **Mean:** {returns.get('daily_mean', 0):.4%}")
            md.append(f"- **Std Dev:** {returns.get('daily_std', 0):.4%}")
            md.append(f"- **Min (worst day):** {returns.get('daily_min', 0):.4%}")
            md.append(f"- **Max (best day):** {returns.get('daily_max', 0):.4%}")
            md.append("")
            md.append("### Period Performance")
            md.append("")
            md.append(f"- **Cumulative Return:** {returns.get('cumulative_return', 0):.2%}")
            md.append(f"- **Annualized Return:** {returns.get('annualized_return', 0):.2%}")
            md.append("")
            md.append("### Trading Statistics")
            md.append("")
            md.append(f"- **Total Days:** {returns.get('total_trading_days', 0)}")
            md.append(f"- **Positive Days:** {returns.get('positive_days', 0)}")
            md.append(f"- **Negative Days:** {returns.get('negative_days', 0)}")
            md.append(f"- **Win Rate:** {returns.get('win_rate', 0):.2%}")
            md.append("")

        # Volatility Analysis
        md.append("## Volatility Analysis")
        md.append("")
        if "volatility" in metrics and metrics["volatility"]:
            vol = metrics["volatility"]
            md.append(f"- **Daily Volatility:** {vol.get('daily_volatility', 0):.4%}")
            md.append(f"- **Annualized Volatility:** {vol.get('annualized_volatility', 0):.2%}")
            md.append(f"- **Downside Deviation:** {vol.get('downside_deviation', 0):.2%}")
            md.append("")

        # Risk-Adjusted Returns
        md.append("## Risk-Adjusted Returns")
        md.append("")
        sharpe = metrics.get("sharpe_ratio", 0)
        sortino = metrics.get("sortino_ratio", 0)
        information = metrics.get("information_ratio", 0)
        calmar = metrics.get("calmar_ratio", 0)

        md.append(f"- **Sharpe Ratio:** {sharpe:.2f}")
        if sharpe > 1:
            md.append("  - Good risk-adjusted performance")
        elif sharpe > 0:
            md.append("  - Positive but modest risk-adjusted return")
        else:
            md.append("  - Underperforming risk-free rate")
        md.append("")

        md.append(f"- **Sortino Ratio:** {sortino:.2f}")
        if sortino > sharpe:
            md.append("  - Better downside risk profile than overall volatility suggests")
        md.append("  - (Higher is better - focuses on downside risk)")
        md.append("")

        md.append(f"- **Information Ratio:** {information:.2f}")
        if information > 1.0:
            md.append("  - Excellent active management (outperforming benchmark)")
        elif information > 0.5:
            md.append("  - Good active management")
        elif information > 0:
            md.append("  - Positive excess return vs benchmark")
        else:
            md.append("  - Underperforming benchmark")
        md.append("  - (Measures skill vs benchmark - accounts for tracking error)")
        md.append("")

        md.append(f"- **Calmar Ratio:** {calmar:.2f}")
        if calmar > 3.0:
            md.append("  - Excellent return relative to maximum drawdown")
        elif calmar > 1.0:
            md.append("  - Good return-to-drawdown ratio")
        else:
            md.append("  - High drawdown risk relative to return")
        md.append("  - (Return per unit of maximum loss)")
        md.append("")

        # Drawdown Analysis
        md.append("## Drawdown Analysis")
        md.append("")
        if "drawdown" in metrics and metrics["drawdown"]:
            dd = metrics["drawdown"]
            md.append(f"- **Maximum Drawdown:** {dd.get('max_drawdown', 0):.2%}")
            md.append(f"- **Max DD Date:** {dd.get('max_drawdown_date', 'N/A')}")
            md.append(f"- **Current Drawdown:** {dd.get('current_drawdown', 0):.2%}")
            md.append(f"- **Days Since Peak:** {dd.get('days_since_peak', 0)}")
            if dd.get('recovery_days'):
                md.append(f"- **Recovery Time:** {dd.get('recovery_days')} days")
            md.append(f"- **At Peak:** {'Yes' if dd.get('is_recovered') else 'No'}")
            md.append("")

        # Market Risk
        md.append("## Market Risk (vs Benchmark)")
        md.append("")
        if "market_risk" in metrics and metrics["market_risk"]:
            mr = metrics["market_risk"]
            md.append(f"**Benchmark:** {mr.get('benchmark', 'N/A')}")
            md.append("")
            md.append(f"- **Beta:** {mr.get('beta', 0):.2f}")
            if mr.get('beta', 0) > 1:
                md.append("  - More volatile than market")
            elif mr.get('beta', 0) < 1:
                md.append("  - Less volatile than market")
            else:
                md.append("  - Moves with market")
            md.append(f"- **Alpha:** {mr.get('alpha', 0):.2%}")
            if mr.get('alpha', 0) > 0:
                md.append("  - Outperforming benchmark (risk-adjusted)")
            md.append(f"- **Correlation:** {mr.get('correlation', 0):.2f}")
            md.append(f"- **R-squared:** {mr.get('r_squared', 0):.2%}")
            md.append("")

        # Tail Risk (VaR)
        md.append("## Tail Risk (Value at Risk)")
        md.append("")
        if "var_95" in metrics and metrics["var_95"]:
            var95 = metrics["var_95"]
            md.append("### 95% Confidence Level")
            md.append("")
            md.append(f"- **VaR (Historical):** {var95.get('var_historical', 0):.2%}")
            md.append(f"- **CVaR (Expected):** {var95.get('cvar_historical', 0):.2%}")
            md.append(f"- **VaR (Parametric):** {var95.get('var_parametric', 0):.2%}")
            md.append("- *5% chance of losing more than VaR in a day*")
            md.append("")

        if "var_99" in metrics and metrics["var_99"]:
            var99 = metrics["var_99"]
            md.append("### 99% Confidence Level")
            md.append("")
            md.append(f"- **VaR (Historical):** {var99.get('var_historical', 0):.2%}")
            md.append(f"- **CVaR (Expected):** {var99.get('cvar_historical', 0):.2%}")
            md.append("- *1% chance of losing more than VaR in a day*")
            md.append("")
            md.append(f"**Worst Historical Day:** {var99.get('worst_day', 0):.2%}")
            md.append("")

        # Rolling Risk-Adjusted Ratios
        md.append("## Rolling Risk-Adjusted Ratios")
        md.append("")
        if "rolling_ratios" in metrics and metrics["rolling_ratios"]:
            rolling = metrics["rolling_ratios"]
            md.append("*Performance consistency over different time windows*")
            md.append("")

            for window_key in ["sharpe_30d", "sharpe_60d", "sharpe_90d"]:
                if window_key in rolling:
                    window_days = window_key.split("_")[1]
                    data = rolling[window_key]
                    md.append(f"### {window_days.upper()} Rolling Sharpe Ratio")
                    md.append("")
                    md.append(f"- **Current:** {data.get('current', 0):.2f}")
                    md.append(f"- **Mean:** {data.get('mean', 0):.2f}")
                    md.append(f"- **Range:** {data.get('min', 0):.2f} to {data.get('max', 0):.2f}")
                    md.append(f"- **Std Dev:** {data.get('std', 0):.2f}")
                    md.append("")

            for window_key in ["sortino_30d", "sortino_60d", "sortino_90d"]:
                if window_key in rolling:
                    window_days = window_key.split("_")[1]
                    data = rolling[window_key]
                    md.append(f"### {window_days.upper()} Rolling Sortino Ratio")
                    md.append("")
                    md.append(f"- **Current:** {data.get('current', 0):.2f}")
                    md.append(f"- **Mean:** {data.get('mean', 0):.2f}")
                    md.append(f"- **Range:** {data.get('min', 0):.2f} to {data.get('max', 0):.2f}")
                    md.append(f"- **Std Dev:** {data.get('std', 0):.2f}")
                    md.append("")

        # Write file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"Risk analysis markdown saved: {output_file}")


# Convenience function
def generate_report(ticker: str, period: str = "1y", output_format: str = "both") -> Dict[str, Any]:
    """Quick report generation"""
    generator = ReportGenerator()
    return generator.generate_full_report(ticker, period=period, output_format=output_format)
