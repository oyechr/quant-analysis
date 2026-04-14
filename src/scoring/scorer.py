"""
Composite Stock Scorer
Combines dimension scores into a single composite score with signal and confidence.
Designed for dual-purpose use: standalone analysis and LLM-optimized output.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import ScoringConfig
from .dimensions import (
    DimensionResult,
    FundamentalScorer,
    RiskScorer,
    TechnicalScorer,
    ValuationScorer,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Complete scoring result for a stock"""

    ticker: str
    composite_score: float  # 0-100
    signal: str  # "Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"
    confidence: str  # "High", "Medium", "Low"
    confidence_score: float  # 0-1

    # Dimension scores
    technical: Optional[DimensionResult] = None
    fundamental: Optional[DimensionResult] = None
    risk: Optional[DimensionResult] = None
    valuation: Optional[DimensionResult] = None

    # Aggregated insights
    strengths: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)

    # Metadata
    generated_at: str = ""
    config_name: str = "default"
    dimensions_available: int = 0
    dimensions_total: int = 4

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary"""
        result = {
            "ticker": self.ticker,
            "composite_score": round(self.composite_score, 1),
            "signal": self.signal,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 2),
            "dimensions": {},
            "strengths": self.strengths,
            "concerns": self.concerns,
            "metadata": {
                "generated_at": self.generated_at,
                "config_name": self.config_name,
                "dimensions_available": self.dimensions_available,
                "dimensions_total": self.dimensions_total,
            },
        }

        if self.technical:
            result["dimensions"]["technical"] = self.technical.to_dict()
        if self.fundamental:
            result["dimensions"]["fundamental"] = self.fundamental.to_dict()
        if self.risk:
            result["dimensions"]["risk"] = self.risk.to_dict()
        if self.valuation:
            result["dimensions"]["valuation"] = self.valuation.to_dict()

        return result

    def format_scorecard(self) -> str:
        """
        Format as a human-readable scorecard string.

        Returns:
            Multi-line scorecard string for terminal/report display
        """
        lines = []
        lines.append("=" * 60)
        lines.append(f"  STOCK SCORE: {self.ticker}")
        lines.append("=" * 60)
        lines.append("")
        lines.append(
            f"  Composite Score:  {self.composite_score:.0f}/100  ({self.signal})"
        )
        lines.append(f"  Confidence:       {self.confidence} ({self.confidence_score:.0%})")
        lines.append("")
        lines.append("-" * 60)
        lines.append("  DIMENSION BREAKDOWN")
        lines.append("-" * 60)

        dimensions = [
            ("Technical", self.technical),
            ("Fundamental", self.fundamental),
            ("Risk", self.risk),
            ("Valuation", self.valuation),
        ]

        for name, dim in dimensions:
            if dim:
                bar = self._score_bar(dim.score)
                lines.append(f"  {name:<14} {dim.score:5.1f}/100  {bar}  [{dim.data_coverage:.0%} data]")
            else:
                lines.append(f"  {name:<14}   N/A       [no data]")

        if self.strengths:
            lines.append("")
            lines.append("-" * 60)
            lines.append("  STRENGTHS")
            lines.append("-" * 60)
            for s in self.strengths[:5]:
                lines.append(f"  + {s}")

        if self.concerns:
            lines.append("")
            lines.append("-" * 60)
            lines.append("  CONCERNS")
            lines.append("-" * 60)
            for c in self.concerns[:5]:
                lines.append(f"  - {c}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def format_for_toon(self) -> Dict[str, Any]:
        """
        Format scoring as a compact dict optimized for TOON serialization and LLM consumption.
        Designed to be inserted at the top of a TOON report for LLM pre-processing.

        Returns:
            Compact dict with scoring summary
        """
        result: Dict[str, Any] = {
            "composite_score": round(self.composite_score, 1),
            "signal": self.signal,
            "confidence": self.confidence,
        }

        dim_scores: Dict[str, Any] = {}
        for name, dim in [
            ("technical", self.technical),
            ("fundamental", self.fundamental),
            ("risk", self.risk),
            ("valuation", self.valuation),
        ]:
            if dim:
                dim_scores[name] = round(dim.score, 1)

        result["dimension_scores"] = dim_scores

        if self.strengths:
            result["strengths"] = self.strengths[:5]
        if self.concerns:
            result["concerns"] = self.concerns[:5]

        return result

    def format_llm_context(self) -> str:
        """
        Generate a structured prompt fragment for LLM consumption.
        Designed to be prepended to TOON report for anchored LLM analysis.

        Returns:
            Formatted string block for LLM instructions
        """
        lines = []
        lines.append("QUANTITATIVE ASSESSMENT:")

        # Headline
        dim_parts = []
        if self.technical:
            dim_parts.append(f"Technical {self.technical.score:.0f}")
        if self.fundamental:
            dim_parts.append(f"Fundamental {self.fundamental.score:.0f}")
        if self.risk:
            dim_parts.append(f"Risk {self.risk.score:.0f}")
        if self.valuation:
            dim_parts.append(f"Valuation {self.valuation.score:.0f}")

        lines.append(
            f"Overall Score: {self.composite_score:.0f}/100 ({self.signal}) "
            f"| Confidence: {self.confidence}"
        )
        if dim_parts:
            lines.append(" | ".join(dim_parts))

        if self.strengths:
            lines.append(f"Strengths: {'; '.join(self.strengths[:3])}")
        if self.concerns:
            lines.append(f"Concerns: {'; '.join(self.concerns[:3])}")

        return "\n".join(lines)

    @staticmethod
    def _score_bar(score: float, width: int = 20) -> str:
        """Create a visual score bar"""
        filled = int(score / 100 * width)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"


class StockScorer:
    """
    Composite Scoring Engine for stock analysis.

    Combines Technical, Fundamental, Risk, and Valuation analysis into
    a single weighted composite score (0-100) with signal classification
    and confidence tracking.

    Usage:
        scorer = StockScorer()
        result = scorer.score(report_data)
        print(result.format_scorecard())

    Or from individual analysis JSONs:
        result = scorer.score_from_analyses(
            technical_data=tech_json,
            fundamental_data=fund_json,
            risk_data=risk_json,
            valuation_data=val_json,
            ticker_info=info_dict,
            ticker="AAPL"
        )
    """

    def __init__(self, config: Optional[ScoringConfig] = None):
        """
        Initialize StockScorer.

        Args:
            config: Scoring configuration. Uses defaults if not provided.
                    Use ScoringConfig.value_investor(), .growth_investor(), etc. for presets.
        """
        self.config = config or ScoringConfig()
        self.technical_scorer = TechnicalScorer(self.config)
        self.fundamental_scorer = FundamentalScorer(self.config)
        self.risk_scorer = RiskScorer(self.config)
        self.valuation_scorer = ValuationScorer(self.config)

    def score(self, report_data: Dict[str, Any]) -> ScoringResult:
        """
        Score a stock from a full report data dictionary.

        Args:
            report_data: Full report dict (as produced by ReportGenerator.generate_full_report())
                        Expected keys: ticker, info, technical_analysis, fundamental_analysis,
                        risk_analysis, valuation_analysis

        Returns:
            ScoringResult with composite score, signals, and dimension breakdowns
        """
        ticker = report_data.get("ticker", "UNKNOWN")
        ticker_info = report_data.get("info", {})

        return self.score_from_analyses(
            technical_data=report_data.get("technical_analysis"),
            fundamental_data=report_data.get("fundamental_analysis"),
            risk_data=report_data.get("risk_analysis"),
            valuation_data=report_data.get("valuation_analysis"),
            ticker_info=ticker_info,
            ticker=ticker,
        )

    def score_from_analyses(
        self,
        technical_data: Optional[Dict[str, Any]] = None,
        fundamental_data: Optional[Dict[str, Any]] = None,
        risk_data: Optional[Dict[str, Any]] = None,
        valuation_data: Optional[Dict[str, Any]] = None,
        ticker_info: Optional[Dict[str, Any]] = None,
        ticker: str = "UNKNOWN",
    ) -> ScoringResult:
        """
        Score a stock from individual analysis data dictionaries.

        Args:
            technical_data: Technical analysis JSON (from TechnicalAnalyzer)
            fundamental_data: Fundamental analysis JSON (from FundamentalAnalyzer)
            risk_data: Risk analysis JSON (from RiskMetrics)
            valuation_data: Valuation analysis JSON (from ValuationAnalyzer)
            ticker_info: Ticker info dict with P/E, PEG, ROE, etc.
            ticker: Stock ticker symbol

        Returns:
            ScoringResult with composite score, signals, and dimension breakdowns
        """
        dimensions: List[tuple] = []  # (weight_attr, DimensionResult)
        all_strengths: List[str] = []
        all_concerns: List[str] = []

        # Score each available dimension
        technical_result = None
        if technical_data:
            try:
                technical_result = self.technical_scorer.score(technical_data)
                dimensions.append(("technical", technical_result))
                all_strengths.extend(technical_result.strengths)
                all_concerns.extend(technical_result.concerns)
            except Exception as e:
                logger.warning(f"Error scoring technical dimension: {e}")

        fundamental_result = None
        if fundamental_data:
            try:
                fundamental_result = self.fundamental_scorer.score(
                    fundamental_data, ticker_info
                )
                dimensions.append(("fundamental", fundamental_result))
                all_strengths.extend(fundamental_result.strengths)
                all_concerns.extend(fundamental_result.concerns)
            except Exception as e:
                logger.warning(f"Error scoring fundamental dimension: {e}")

        risk_result = None
        if risk_data:
            try:
                risk_result = self.risk_scorer.score(risk_data)
                dimensions.append(("risk", risk_result))
                all_strengths.extend(risk_result.strengths)
                all_concerns.extend(risk_result.concerns)
            except Exception as e:
                logger.warning(f"Error scoring risk dimension: {e}")

        valuation_result = None
        if valuation_data:
            try:
                valuation_result = self.valuation_scorer.score(valuation_data, ticker_info)
                dimensions.append(("valuation", valuation_result))
                all_strengths.extend(valuation_result.strengths)
                all_concerns.extend(valuation_result.concerns)
            except Exception as e:
                logger.warning(f"Error scoring valuation dimension: {e}")

        # Calculate composite score with weight normalization
        composite_score = self._calculate_composite(dimensions)

        # Calculate confidence based on data coverage
        confidence_score = self._calculate_confidence(dimensions)
        confidence_label = self._confidence_label(confidence_score)

        # Get signal
        signal = self.config.get_signal(composite_score)

        return ScoringResult(
            ticker=ticker,
            composite_score=composite_score,
            signal=signal,
            confidence=confidence_label,
            confidence_score=confidence_score,
            technical=technical_result,
            fundamental=fundamental_result,
            risk=risk_result,
            valuation=valuation_result,
            strengths=all_strengths,
            concerns=all_concerns,
            generated_at=datetime.now().isoformat(),
            dimensions_available=len(dimensions),
            dimensions_total=4,
        )

    def _calculate_composite(
        self, dimensions: List[tuple]
    ) -> float:
        """
        Calculate weighted composite score from available dimensions.
        Re-normalizes weights when some dimensions are missing.
        """
        if not dimensions:
            return 50.0

        total_weight = 0.0
        weighted_sum = 0.0

        for weight_attr, dim_result in dimensions:
            weight = getattr(self.config.weights, weight_attr, 0.25)
            weighted_sum += dim_result.score * weight
            total_weight += weight

        if total_weight > 0:
            return weighted_sum / total_weight
        return 50.0

    def _calculate_confidence(
        self, dimensions: List[tuple]
    ) -> float:
        """
        Calculate confidence score (0-1) based on:
        1. Number of dimensions available (40% weight)
        2. Average data coverage within available dimensions (60% weight)
        """
        if not dimensions:
            return 0.0

        # Factor 1: Dimension availability (4 dimensions = 100%)
        dim_availability = len(dimensions) / 4.0

        # Factor 2: Average data coverage across available dimensions
        avg_coverage = sum(d.data_coverage for _, d in dimensions) / len(dimensions)

        return (dim_availability * 0.4) + (avg_coverage * 0.6)

    @staticmethod
    def _confidence_label(confidence_score: float) -> str:
        """Convert confidence score to label"""
        if confidence_score >= 0.75:
            return "High"
        elif confidence_score >= 0.50:
            return "Medium"
        else:
            return "Low"
