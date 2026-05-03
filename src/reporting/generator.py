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
from ..scoring import ScoringConfig, StockScorer
from ..utils.toon_serializer import report_to_toon
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
    ValuationAnalysisSection,
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
        output_format: str = "all",
        use_cache: bool = True,
        include_technical: bool = True,
        include_fundamental: bool = True,
        include_risk: bool = True,
        include_valuation: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate comprehensive report with all available data

        By default, includes all analysis types (technical, fundamental, risk, valuation).
        Set individual flags to False to exclude specific analyses.

        Args:
            ticker: Stock ticker symbol
            period: Period for price data (1mo, 3mo, 6mo, 1y, 2y, 5y, etc.)
            output_format: "json", "markdown", "toon", or "all" (json+markdown+toon)
            use_cache: Whether to use cached data
            include_technical: Whether to include technical analysis (default: True)
            include_fundamental: Whether to include fundamental analysis (default: True)
            include_risk: Whether to include risk metrics and performance analysis (default: True)
            include_valuation: Whether to include valuation analysis - DCF, DDM, dividends, earnings (default: True)

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

        # Add valuation analysis if requested
        valuation_analyzer = None
        if include_valuation:
            try:
                from ..analysis import ValuationAnalyzer

                # Fetch required data
                price_data = self.fetcher.fetch_ticker(ticker, period="1y", use_cache=use_cache)
                fundamentals = self.fetcher.fetch_fundamentals(ticker, use_cache=use_cache)
                earnings_data = self.fetcher.fetch_earnings(ticker, use_cache=use_cache)

                # Fetch dividends and convert to Series
                div_data = self.fetcher.fetch_dividends(ticker, use_cache=use_cache)
                dividends_series = None
                if div_data and div_data.get("dividends") is not None:
                    dividends_df = div_data["dividends"]
                    if not dividends_df.empty:
                        # Check if Date is already the index or a column
                        if "Date" in dividends_df.columns:
                            dividends_series = dividends_df.set_index("Date")["Dividends"]
                        elif dividends_df.index.name == "Date":
                            dividends_series = dividends_df["Dividends"]
                        else:
                            logger.warning("Dividends DataFrame has unexpected structure")
                            dividends_series = dividends_df.iloc[:, 0]  # Fallback to first column

                # Create analyzer
                valuation_analyzer = ValuationAnalyzer(
                    ticker=ticker,
                    ticker_info=report_data.get("info", {}),
                    price_data=price_data,
                    fundamentals=fundamentals,
                    earnings_data=earnings_data,
                    dividends_data=dividends_series,
                )

                # Run analysis
                valuation_results = valuation_analyzer.analyze()
                report_data["valuation_analysis"] = valuation_results
            except Exception as e:
                logger.error(f"Error processing valuation analysis: {e}")
                report_data["valuation_analysis"] = None

        # Run Composite Scoring Engine
        scoring_result = None
        try:
            scorer = StockScorer()
            scoring_result = scorer.score(report_data)
            report_data["scoring"] = scoring_result.to_dict()
            logger.info(
                f"Scoring complete: {scoring_result.composite_score:.1f}/100 "
                f"({scoring_result.signal})"
            )
        except Exception as e:
            logger.error(f"Error running scoring engine: {e}")
            report_data["scoring"] = None

        # Save outputs
        if output_format in ["json", "all"]:
            self._save_json_report(ticker, report_data)

        if output_format in ["markdown", "all"]:
            self._save_markdown_report(
                ticker,
                report_data,
                technical_analyzer,
                fundamental_analyzer,
                risk_analyzer_tuple,
                valuation_analyzer,
                scoring_result,
            )

        if output_format in ["toon", "all"]:
            self._save_toon_report(ticker, report_data)

        # Save separate scoring report
        if scoring_result:
            self._save_scoring_json(ticker, scoring_result)
            self._save_scoring_markdown(ticker, scoring_result)

        logger.info(f"Report generation complete for {ticker}")
        return report_data

    def _get_reports_dir(self, ticker: str) -> Path:
        """Get (and create) reports directory for a ticker"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir

    def _save_analysis_files(
        self,
        ticker: str,
        report_type: str,
        json_data: Optional[Dict[str, Any]] = None,
        markdown_lines: Optional[List[str]] = None,
    ):
        """
        Save analysis as JSON and/or markdown files

        Args:
            ticker: Stock ticker symbol
            report_type: Base filename (e.g., 'technical_analysis', 'risk_analysis')
            json_data: Data to save as JSON (if provided)
            markdown_lines: Markdown lines to save (if provided)
        """
        reports_dir = self._get_reports_dir(ticker)

        if json_data is not None:
            output_file = reports_dir / f"{report_type}.json"
            with open(output_file, "w") as f:
                json.dump(json_data, f, indent=2, default=str)
            logger.info(f"{report_type.replace('_', ' ').title()} JSON saved: {output_file}")

        if markdown_lines is not None:
            output_file = reports_dir / f"{report_type}.md"
            md = [
                f"# {ticker} - {report_type.replace('_', ' ').title()} Report",
                "",
                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            md.extend(markdown_lines)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("\n".join(md))
            logger.info(f"{report_type.replace('_', ' ').title()} markdown saved: {output_file}")

    def _save_json_report(self, ticker: str, data: Dict[str, Any]):
        """Save report as JSON"""
        reports_dir = self._get_reports_dir(ticker)
        output_file = reports_dir / "full_report.json"
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"JSON report saved: {output_file}")

    def _save_toon_report(self, ticker: str, data: Dict[str, Any]):
        """Save report as TOON (Token-Oriented Object Notation) for LLM consumption"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "full_report.toon"

        # If scoring is available, build a report with scoring summary at the top
        # so the LLM reads the quantitative assessment first
        toon_data = dict(data)
        scoring = data.get("scoring")
        if scoring:
            # Renamed to 'scoring_summary' in TOON output to position it first
            # and signal to LLMs that this is a pre-computed summary. The full
            # scoring data remains under 'scoring' in the JSON report.
            toon_data = {"scoring_summary": scoring}
            for key, value in data.items():
                if key != "scoring":
                    toon_data[key] = value

        toon_str = report_to_toon(toon_data)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(toon_str)
        logger.info(f"TOON report saved: {output_file}")

    def _save_markdown_report(
        self,
        ticker: str,
        data: Dict[str, Any],
        technical_analyzer=None,
        fundamental_analyzer=None,
        risk_analyzer_tuple=None,
        valuation_analyzer=None,
        scoring_result=None,
    ):
        """Save report as Markdown using section handlers"""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "report.md"

        md = []
        md.append(f"# {ticker} - Comprehensive Stock Report")
        md.append(f"\n**Generated:** {data['generated_at']}")
        md.append(f"\n**Period:** {data['period']}")

        # Insert Stock Score at the top of the report
        if scoring_result:
            md.append("")
            md.append("---")
            md.append("")
            md.append("```")
            md.append(scoring_result.format_scorecard())
            md.append("```")
            md.append("")
            md.append("---")

        # Generate markdown for each section using handlers
        currency = data.get("info", {}).get("currency", "USD")
        for section_name, section in self.sections.items():
            section_data = data.get(section_name)
            if section_data is not None:
                try:
                    # Each section handler formats its own markdown
                    md.extend(section.format_for_markdown(section_data, currency=currency))
                except Exception as e:
                    logger.warning(f"Error formatting markdown for {section_name}: {e}")

        # Add fundamental analysis summary if available
        if fundamental_analyzer and data.get("fundamental_analysis"):
            try:
                fund_section = FundamentalAnalysisSection()
                md.extend(
                    fund_section.format_for_markdown(
                        data["fundamental_analysis"], currency=currency
                    )
                )
            except Exception as e:
                logger.warning(f"Error formatting fundamental analysis markdown: {e}")

        # Add technical analysis summary if available
        if technical_analyzer and data.get("technical_analysis"):
            try:
                tech_section = TechnicalAnalysisSection()
                md.extend(tech_section.format_for_markdown(technical_analyzer, currency=currency))
            except Exception as e:
                logger.warning(f"Error formatting technical analysis markdown: {e}")

        # Add risk analysis summary if available
        if risk_analyzer_tuple and data.get("risk_analysis"):
            try:
                risk_section = RiskAnalysisSection()
                md.extend(risk_section.format_for_markdown(risk_analyzer_tuple, currency=currency))
            except Exception as e:
                logger.warning(f"Error formatting risk analysis markdown: {e}")

        # Add valuation analysis summary if available
        if valuation_analyzer and data.get("valuation_analysis"):
            try:
                val_section = ValuationAnalysisSection()
                md.extend(
                    val_section.format_for_markdown(data["valuation_analysis"], currency=currency)
                )
            except Exception as e:
                logger.warning(f"Error formatting valuation analysis markdown: {e}")

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

        # Save detailed valuation analysis markdown if available
        if valuation_analyzer:
            self._save_valuation_markdown(ticker, valuation_analyzer)
            valuation_results = valuation_analyzer.analyze()
            self._save_valuation_json(ticker, valuation_results)

    def _save_technical_json(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate JSON file"""
        self._save_analysis_files(
            ticker, "technical_analysis",
            json_data=technical_analyzer.get_summary(),
        )

    def _save_technical_markdown(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate markdown file"""
        self._save_analysis_files(
            ticker, "technical_analysis",
            markdown_lines=technical_analyzer.format_markdown(),
        )

    def _save_fundamental_json(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate JSON file"""
        self._save_analysis_files(
            ticker, "fundamental_analysis",
            json_data=fundamental_analyzer.get_summary(),
        )

    def _save_fundamental_markdown(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate markdown file"""
        self._save_analysis_files(
            ticker, "fundamental_analysis",
            markdown_lines=fundamental_analyzer.format_markdown(),
        )

    def _save_risk_json(self, ticker: str, risk_analyzer_tuple):
        """Save detailed risk analysis as separate JSON file"""
        if not isinstance(risk_analyzer_tuple, tuple) or len(risk_analyzer_tuple) < 2:
            logger.warning("Invalid risk analyzer data for JSON export")
            return
        _, metrics, _ = risk_analyzer_tuple
        self._save_analysis_files(ticker, "risk_analysis", json_data=metrics)

    def _save_risk_markdown(self, ticker: str, risk_analyzer_tuple):
        """Save detailed risk analysis as separate markdown file"""
        if not isinstance(risk_analyzer_tuple, tuple) or len(risk_analyzer_tuple) < 2:
            logger.warning("Invalid risk analyzer data for markdown export")
            return
        risk_analyzer, metrics, _ = risk_analyzer_tuple
        self._save_analysis_files(
            ticker, "risk_analysis",
            markdown_lines=risk_analyzer.format_markdown(ticker=ticker, metrics=metrics),
        )

    def _save_valuation_json(self, ticker: str, valuation_data: Dict[str, Any]):
        """Save detailed valuation analysis as separate JSON file"""
        self._save_analysis_files(ticker, "valuation_analysis", json_data=valuation_data)

    def _save_valuation_markdown(self, ticker: str, valuation_analyzer):
        """Save detailed valuation analysis as separate markdown file"""
        self._save_analysis_files(
            ticker, "valuation_analysis",
            markdown_lines=valuation_analyzer.format_markdown(),
        )

    def _save_scoring_json(self, ticker: str, scoring_result):
        """Save scoring results as separate JSON file"""
        self._save_analysis_files(
            ticker, "scoring",
            json_data=scoring_result.to_dict(),
        )

    def _save_scoring_markdown(self, ticker: str, scoring_result):
        """Save scoring results as separate markdown file"""
        reports_dir = self._get_reports_dir(ticker)
        output_file = reports_dir / "scoring.md"

        md = []
        md.append(f"# {ticker} - Stock Score Report")
        md.append("")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md.append("")
        md.append("```")
        md.append(scoring_result.format_scorecard())
        md.append("```")
        md.append("")

        # Detailed dimension breakdown
        for name, dim in [
            ("Technical", scoring_result.technical),
            ("Fundamental", scoring_result.fundamental),
            ("Risk", scoring_result.risk),
            ("Valuation", scoring_result.valuation),
        ]:
            if dim:
                md.append(f"## {name} Analysis ({dim.score:.1f}/100)")
                md.append("")
                md.append(f"Data coverage: {dim.data_coverage:.0%}")
                md.append("")
                md.append("| Metric | Score | Weight | Raw Value | Label |")
                md.append("|--------|-------|--------|-----------|-------|")
                for s in dim.sub_scores:
                    avail = "" if s.available else " *(N/A)*"
                    raw = f"{s.raw_value}" if s.raw_value is not None else "—"
                    md.append(
                        f"| {s.name}{avail} | {s.score:.1f} | {s.weight:.0%} | {raw} | {s.label} |"
                    )
                md.append("")

        # LLM Context section
        md.append("## LLM Context Block")
        md.append("")
        md.append("*The following block is designed to be prepended to TOON reports for LLM analysis:*")
        md.append("")
        md.append("```")
        md.append(scoring_result.format_llm_context())
        md.append("```")
        md.append("")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"Scoring markdown saved: {output_file}")
