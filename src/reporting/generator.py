"""
Report Generator Module
Aggregates and formats data from DataFetcher into comprehensive reports
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisBundle, AnalysisOptions, analyze_ticker
from ..scoring import ScoringConfig
from ..utils.toon_serializer import report_to_toon
from .markdown import render_report_markdown

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
        self.fetcher = data_fetcher or DataFetcher(cache_dir=output_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

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
        scoring_config: Optional[ScoringConfig] = None,
    ) -> Dict[str, Any]:
        """
        Generate comprehensive report with all available data

        By default, includes all analysis types (technical, fundamental, risk, valuation).
        Set individual flags to False to exclude specific analyses.

        Args:
            ticker: Stock ticker symbol
            period: Period for price data (1mo, 3mo, 6mo, 1y, 2y, 5y, etc.)
            output_format: "json", "markdown", "toon", "all" (json+markdown+toon),
                or "none" (compute only, write nothing)
            use_cache: Whether to use cached data
            include_technical: Whether to include technical analysis (default: True)
            include_fundamental: Whether to include fundamental analysis (default: True)
            include_risk: Whether to include risk metrics and performance analysis (default: True)
            include_valuation: Whether to include valuation analysis - DCF, DDM, dividends, earnings (default: True)
            scoring_config: Scoring preset (default weights if None)

        Returns:
            Dictionary with all fetched data and metadata
        """
        return self.generate(
            ticker,
            AnalysisOptions(
                period=period,
                use_cache=use_cache,
                include_technical=include_technical,
                include_fundamental=include_fundamental,
                include_risk=include_risk,
                include_valuation=include_valuation,
                scoring_config=scoring_config,
            ),
            output_format=output_format,
        ).report

    def generate(
        self,
        ticker: str,
        options: Optional[AnalysisOptions] = None,
        output_format: str = "all",
    ) -> AnalysisBundle:
        """
        Run the analysis pipeline for a ticker and save report files.

        Returns:
            AnalysisBundle with the report dict, scoring result, and analyzers
        """
        bundle = analyze_ticker(ticker, fetcher=self.fetcher, options=options)
        ticker = bundle.ticker
        report_data = bundle.report

        if output_format in ["json", "all"]:
            self._save_json_report(ticker, report_data)

        if output_format in ["markdown", "all"]:
            self._save_markdown_report(
                ticker,
                report_data,
                bundle.technical,
                bundle.fundamental,
                bundle.risk,
                bundle.valuation,
                bundle.scoring,
            )

        if output_format in ["toon", "all"]:
            self._save_toon_report(ticker, report_data)

        # Save separate scoring report
        if bundle.scoring and output_format != "none":
            self._save_scoring_json(ticker, bundle.scoring)
            self._save_scoring_markdown(ticker, bundle.scoring)

        logger.info(f"Report generation complete for {ticker}")
        return bundle

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
        """Save report.md (see markdown.render_report_markdown) and the per-analysis files."""
        reports_dir = self.output_dir / ticker / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / "report.md"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(render_report_markdown(ticker, data, scoring_result))

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
            self._save_valuation_json(ticker, valuation_analyzer.analyze())

    def _save_technical_json(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate JSON file"""
        self._save_analysis_files(
            ticker,
            "technical_analysis",
            json_data=technical_analyzer.get_summary(),
        )

    def _save_technical_markdown(self, ticker: str, technical_analyzer):
        """Save detailed technical analysis as separate markdown file"""
        self._save_analysis_files(
            ticker,
            "technical_analysis",
            markdown_lines=technical_analyzer.format_markdown(),
        )

    def _save_fundamental_json(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate JSON file"""
        self._save_analysis_files(
            ticker,
            "fundamental_analysis",
            json_data=fundamental_analyzer.get_summary(),
        )

    def _save_fundamental_markdown(self, ticker: str, fundamental_analyzer):
        """Save detailed fundamental analysis as separate markdown file"""
        self._save_analysis_files(
            ticker,
            "fundamental_analysis",
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
            ticker,
            "risk_analysis",
            markdown_lines=risk_analyzer.format_markdown(ticker=ticker, metrics=metrics),
        )

    def _save_valuation_json(self, ticker: str, valuation_data: Dict[str, Any]):
        """Save detailed valuation analysis as separate JSON file"""
        self._save_analysis_files(ticker, "valuation_analysis", json_data=valuation_data)

    def _save_valuation_markdown(self, ticker: str, valuation_analyzer):
        """Save detailed valuation analysis as separate markdown file"""
        self._save_analysis_files(
            ticker,
            "valuation_analysis",
            markdown_lines=valuation_analyzer.format_markdown(),
        )

    def _save_scoring_json(self, ticker: str, scoring_result):
        """Save scoring results as separate JSON file"""
        self._save_analysis_files(
            ticker,
            "scoring",
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
                    raw = f"{s.raw_value}" if s.raw_value is not None else " - "
                    md.append(
                        f"| {s.name}{avail} | {s.score:.1f} | {s.weight:.0%} | {raw} | {s.label} |"
                    )
                md.append("")

        # LLM Context section
        md.append("## LLM Context Block")
        md.append("")
        md.append(
            "*The following block is designed to be prepended to TOON reports for LLM analysis:*"
        )
        md.append("")
        md.append("```")
        md.append(scoring_result.format_llm_context())
        md.append("```")
        md.append("")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"Scoring markdown saved: {output_file}")
