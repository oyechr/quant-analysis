"""
Composite Stock Scorer
Combines dimension scores into a single composite score with signal and confidence.
Designed for dual-purpose use: standalone analysis and LLM-optimized output.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .config import ScoringConfig
from .dimensions import (
    DimensionResult,
    FundamentalScorer,
    RiskScorer,
    TechnicalScorer,
    ValuationScorer,
)
from .trade_levels import TradeLevelsResult

logger = logging.getLogger(__name__)

# A dimension counts at full weight in the composite from this data coverage
# (the share of its inputs available); below it, the weight falls linearly to
# zero. Half, because some dimensions are partial by design: a bank's
# fundamentals leave out Altman, Beneish and accruals (4 of 8 inputs).
FULL_WEIGHT_COVERAGE = 0.5


def coverage_weight(coverage: float) -> float:
    """The share of its weight a dimension keeps at this data coverage (0-1)."""
    return max(0.0, min(1.0, coverage / FULL_WEIGHT_COVERAGE))


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

    # Trade levels
    trade_levels: Optional[TradeLevelsResult] = None

    # Aggregated insights
    strengths: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)

    # Metadata
    generated_at: str = ""
    config_name: str = "default"
    dimensions_available: int = 0
    dimensions_total: int = 4
    # Dimension (or "trade_levels") -> the error that kept it out. A scorer
    # bug would otherwise just reweight the composite, seen only in the log
    errors: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary"""
        dimensions: Dict[str, Any] = {}
        result: Dict[str, Any] = {
            "ticker": self.ticker,
            "composite_score": round(self.composite_score, 1),
            "signal": self.signal,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 2),
            "dimensions": dimensions,
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
            dimensions["technical"] = self.technical.to_dict()
        if self.fundamental:
            dimensions["fundamental"] = self.fundamental.to_dict()
        if self.risk:
            dimensions["risk"] = self.risk.to_dict()
        if self.valuation:
            dimensions["valuation"] = self.valuation.to_dict()

        if self.trade_levels:
            result["trade_levels"] = self.trade_levels.to_dict()
        if self.errors:
            result["errors"] = dict(self.errors)

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
        lines.append(f"  Composite Score:  {self.composite_score:.0f}/100  ({self.signal})")
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
                lines.append(
                    f"  {name:<14} {dim.score:5.1f}/100  {bar}  [{dim.data_coverage:.0%} data]"
                )
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

        if self.trade_levels:
            lines.append("")
            lines.append(self.trade_levels.format_scorecard())

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

        if self.trade_levels:
            result["trade_levels"] = self.trade_levels.to_dict()

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

        if self.trade_levels:
            from ..utils.report import get_currency_symbol

            sym = get_currency_symbol(self.trade_levels.currency)
            tl = self.trade_levels
            if tl.bullish and tl.bullish.target and tl.bullish.stop_loss:
                lines.append(
                    f"Bullish: entry {sym}{tl.bullish.entry_low:.2f}, "
                    f"target {sym}{tl.bullish.target:.2f}, "
                    f"stop {sym}{tl.bullish.stop_loss:.2f}"
                )
            if tl.bearish and tl.bearish.target and tl.bearish.stop_loss:
                lines.append(
                    f"Bearish: entry {sym}{tl.bearish.entry_low:.2f}, "
                    f"target {sym}{tl.bearish.target:.2f}, "
                    f"stop {sym}{tl.bearish.stop_loss:.2f}"
                )

        return "\n".join(lines)

    @staticmethod
    def _score_bar(score: float, width: int = 20) -> str:
        """Create a visual score bar"""
        filled = int(score / 100 * width)
        empty = width - filled
        return f"[{'#' * filled}{'-' * empty}]"


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

        result = self.score_from_analyses(
            technical_data=report_data.get("technical_analysis"),
            fundamental_data=report_data.get("fundamental_analysis"),
            risk_data=report_data.get("risk_analysis"),
            valuation_data=report_data.get("valuation_analysis"),
            ticker_info=ticker_info,
            ticker=ticker,
            peer_valuation=report_data.get("peer_valuation"),
        )

        # Compute trade levels from full report data
        try:
            from .trade_levels import compute_trade_levels_from_report

            trade_levels = compute_trade_levels_from_report(report_data)
            if trade_levels:
                result.trade_levels = trade_levels
        except Exception as e:
            logger.warning(f"Error computing trade levels: {e}")
            result.errors["trade_levels"] = f"{type(e).__name__}: {e}"

        return result

    def score_from_analyses(
        self,
        technical_data: Optional[Dict[str, Any]] = None,
        fundamental_data: Optional[Dict[str, Any]] = None,
        risk_data: Optional[Dict[str, Any]] = None,
        valuation_data: Optional[Dict[str, Any]] = None,
        ticker_info: Optional[Dict[str, Any]] = None,
        ticker: str = "UNKNOWN",
        peer_valuation: Optional[Dict[str, Any]] = None,
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
            peer_valuation: Optional peer comparison for peer-relative P/E

        Returns:
            ScoringResult with composite score, signals, and dimension breakdowns
        """
        dimensions: List[tuple[str, DimensionResult]] = []  # (weight_attr, result)
        all_strengths: List[str] = []
        all_concerns: List[str] = []

        errors: Dict[str, str] = {}

        def run(name: str, data: Any, fn: Callable[[], DimensionResult]) -> Any:
            if not data:
                return None
            try:
                result = fn()
            except Exception as e:
                # Recorded on the result: the composite is reweighted without it
                logger.warning(f"Error scoring {name} dimension: {e}")
                errors[name] = f"{type(e).__name__}: {e}"
                return None
            dimensions.append((name, result))
            all_strengths.extend(result.strengths)
            all_concerns.extend(result.concerns)
            return result

        fcf_metrics = ((fundamental_data or {}).get("analysis") or {}).get("fcf_metrics") or {}
        technical_result = run(
            "technical", technical_data, lambda: self.technical_scorer.score(technical_data or {})
        )
        fundamental_result = run(
            "fundamental",
            fundamental_data,
            lambda: self.fundamental_scorer.score(fundamental_data or {}, ticker_info),
        )
        risk_result = run("risk", risk_data, lambda: self.risk_scorer.score(risk_data or {}))
        valuation_result = run(
            "valuation",
            valuation_data,
            lambda: self.valuation_scorer.score(
                valuation_data or {},
                ticker_info,
                peer_valuation,
                fcf_yield=fcf_metrics.get("fcf_yield"),
            ),
        )

        # A dimension with no usable data (a fund's statements, say) scores a
        # placeholder 50; keep it for display but out of the composite
        dimensions = [(name, result) for name, result in dimensions if result.data_coverage > 0]

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
            config_name=self.config.name,
            dimensions_available=len(dimensions),
            dimensions_total=4,
            errors=errors,
        )

    def _calculate_composite(self, dimensions: List[tuple[str, DimensionResult]]) -> float:
        """
        Calculate weighted composite score from available dimensions.
        Re-normalizes weights when some dimensions are missing.

        A dimension with thin data counts less: its weight is scaled by
        `coverage_weight`, so a score built from a quarter of its inputs (a
        few info ratios, say) can't carry the composite at full weight.
        """
        if not dimensions:
            return 50.0

        total_weight = 0.0
        weighted_sum = 0.0

        for weight_attr, dim_result in dimensions:
            weight = getattr(self.config.weights, weight_attr, 0.25)
            weight *= coverage_weight(dim_result.data_coverage)
            weighted_sum += dim_result.score * weight
            total_weight += weight

        if total_weight > 0:
            return weighted_sum / total_weight
        return 50.0

    def _calculate_confidence(self, dimensions: List[tuple[str, DimensionResult]]) -> float:
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


def format_score_table(results: Dict[str, Optional[ScoringResult]], preset: str) -> str:
    """One row per ticker (in the dict's order); None marks a ticker that failed."""
    lines = [
        "",
        "=" * 70,
        f"  STOCK SCORES  (preset: {preset})",
        "=" * 70,
        "",
        f"  {'Ticker':<8} {'Score':>6} {'Signal':<12} {'Confidence':<10} {'Tech':>5} "
        f"{'Fund':>5} {'Risk':>5} {'Val':>5}",
        "  " + "-" * 62,
    ]
    for ticker, result in results.items():
        if result is None:
            lines.append(f"  {ticker:<8}    ERROR")
            continue
        tech = f"{result.technical.score:.0f}" if result.technical else "N/A"
        fund = f"{result.fundamental.score:.0f}" if result.fundamental else "N/A"
        risk = f"{result.risk.score:.0f}" if result.risk else "N/A"
        val = f"{result.valuation.score:.0f}" if result.valuation else "N/A"
        lines.append(
            f"  {ticker:<8} {result.composite_score:>5.0f}  {result.signal:<12} "
            f"{result.confidence:<10} {tech:>5} {fund:>5} {risk:>5} {val:>5}"
        )
    lines.append("")
    return "\n".join(lines)
