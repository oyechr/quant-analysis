"""
Scoring Configuration
Defines weights, thresholds, and scoring parameters for the Composite Scoring Engine
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class DimensionWeight:
    """Weights for each scoring dimension (must sum to 1.0)"""

    technical: float = 0.25
    fundamental: float = 0.30
    risk: float = 0.20
    valuation: float = 0.25

    def __post_init__(self):
        total = self.technical + self.fundamental + self.risk + self.valuation
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Dimension weights must sum to 1.0, got {total:.3f}. "
                f"Current: technical={self.technical}, fundamental={self.fundamental}, "
                f"risk={self.risk}, valuation={self.valuation}"
            )


@dataclass
class SignalThresholds:
    """Score thresholds for signal classification"""

    strong_buy: float = 80.0
    buy: float = 65.0
    hold_upper: float = 50.0
    sell: float = 35.0
    # Below sell threshold = Strong Sell


@dataclass
class TechnicalScoringParams:
    """Parameters for technical dimension scoring"""

    # RSI thresholds
    rsi_oversold: float = 30.0  # Below = bullish signal
    rsi_overbought: float = 70.0  # Above = bearish signal
    rsi_neutral_low: float = 40.0
    rsi_neutral_high: float = 60.0

    # MACD
    macd_weight: float = 0.20

    # Moving average alignment
    ma_weight: float = 0.25

    # ADX trend strength
    adx_strong_trend: float = 25.0
    adx_very_strong: float = 40.0

    # MFI thresholds (similar to RSI)
    mfi_oversold: float = 20.0
    mfi_overbought: float = 80.0


@dataclass
class FundamentalScoringParams:
    """Parameters for fundamental dimension scoring"""

    # Piotroski F-Score thresholds
    f_score_strong: int = 8
    f_score_average: int = 5

    # Altman Z-Score thresholds
    z_score_safe: float = 2.99
    z_score_grey: float = 1.81

    # Growth rate thresholds (percentage)
    revenue_growth_strong: float = 15.0
    revenue_growth_moderate: float = 5.0
    earnings_growth_strong: float = 20.0
    earnings_growth_moderate: float = 5.0

    # Margin thresholds
    gross_margin_excellent: float = 40.0
    gross_margin_good: float = 25.0
    operating_margin_excellent: float = 20.0
    operating_margin_good: float = 10.0

    # ROE thresholds
    roe_excellent: float = 20.0
    roe_good: float = 10.0


@dataclass
class RiskScoringParams:
    """Parameters for risk dimension scoring"""

    # Sharpe ratio thresholds
    sharpe_excellent: float = 2.0
    sharpe_good: float = 1.0
    sharpe_acceptable: float = 0.5

    # Maximum drawdown thresholds (absolute values)
    drawdown_low: float = 0.10  # <10% = low risk
    drawdown_moderate: float = 0.20  # 10-20% = moderate
    drawdown_high: float = 0.35  # 20-35% = high

    # Beta thresholds
    beta_ideal_low: float = 0.7
    beta_ideal_high: float = 1.3

    # Volatility thresholds (annualized)
    volatility_low: float = 0.15
    volatility_moderate: float = 0.25
    volatility_high: float = 0.40


@dataclass
class ValuationScoringParams:
    """Parameters for valuation dimension scoring"""

    # DCF discount thresholds (positive = undervalued)
    dcf_deep_discount: float = -30.0  # >30% below intrinsic = deep value
    dcf_moderate_discount: float = -10.0
    dcf_fair_value_range: float = 10.0  # Within 10% of intrinsic

    # P/E thresholds
    pe_undervalued: float = 15.0
    pe_fair: float = 25.0
    pe_expensive: float = 35.0

    # PEG ratio thresholds
    peg_undervalued: float = 1.0
    peg_fair: float = 2.0

    # FCF yield thresholds
    fcf_yield_attractive: float = 5.0
    fcf_yield_moderate: float = 3.0

    # Dividend sustainability
    div_sustainability_excellent: float = 80.0
    div_sustainability_good: float = 60.0

    # Earnings quality
    earnings_beat_rate_strong: float = 75.0
    earnings_beat_rate_moderate: float = 50.0


@dataclass
class ScoringConfig:
    """
    Complete configuration for the Composite Scoring Engine

    Controls weights, thresholds, and parameters for all scoring dimensions.
    Can be customized per investment style (e.g., value, growth, income).
    """

    weights: DimensionWeight = field(default_factory=DimensionWeight)
    signals: SignalThresholds = field(default_factory=SignalThresholds)
    technical: TechnicalScoringParams = field(default_factory=TechnicalScoringParams)
    fundamental: FundamentalScoringParams = field(default_factory=FundamentalScoringParams)
    risk: RiskScoringParams = field(default_factory=RiskScoringParams)
    valuation: ValuationScoringParams = field(default_factory=ValuationScoringParams)

    def get_signal(self, score: float) -> str:
        """
        Convert a composite score to a signal label

        Args:
            score: Composite score (0-100)

        Returns:
            Signal string: "Strong Buy", "Buy", "Hold", "Sell", or "Strong Sell"
        """
        if score >= self.signals.strong_buy:
            return "Strong Buy"
        elif score >= self.signals.buy:
            return "Buy"
        elif score >= self.signals.hold_upper:
            return "Hold"
        elif score >= self.signals.sell:
            return "Sell"
        else:
            return "Strong Sell"

    @classmethod
    def load_from_file(cls, path: Path) -> "ScoringConfig":
        """Load scoring configuration from JSON file"""
        if not path.exists():
            logger.info(f"Scoring config not found at {path}, using defaults")
            return cls()

        try:
            with open(path, "r") as f:
                data = json.load(f)

            config = cls()
            if "weights" in data:
                config.weights = DimensionWeight(**data["weights"])
            if "signals" in data:
                config.signals = SignalThresholds(**data["signals"])
            if "technical" in data:
                config.technical = TechnicalScoringParams(**data["technical"])
            if "fundamental" in data:
                config.fundamental = FundamentalScoringParams(**data["fundamental"])
            if "risk" in data:
                config.risk = RiskScoringParams(**data["risk"])
            if "valuation" in data:
                config.valuation = ValuationScoringParams(**data["valuation"])

            logger.info(f"Loaded scoring configuration from {path}")
            return config

        except Exception as e:
            logger.error(f"Error loading scoring config from {path}: {e}")
            return cls()

    def save_to_file(self, path: Path):
        """Save scoring configuration to JSON file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        logger.info(f"Scoring configuration saved to {path}")

    @classmethod
    def value_investor(cls) -> "ScoringConfig":
        """Preset: Value-oriented investor (emphasizes fundamentals + valuation)"""
        return cls(
            weights=DimensionWeight(
                technical=0.10, fundamental=0.35, risk=0.20, valuation=0.35
            ),
        )

    @classmethod
    def growth_investor(cls) -> "ScoringConfig":
        """Preset: Growth-oriented investor (emphasizes growth + momentum)"""
        return cls(
            weights=DimensionWeight(
                technical=0.30, fundamental=0.35, risk=0.15, valuation=0.20
            ),
        )

    @classmethod
    def income_investor(cls) -> "ScoringConfig":
        """Preset: Income-oriented investor (emphasizes dividends + risk)"""
        return cls(
            weights=DimensionWeight(
                technical=0.10, fundamental=0.25, risk=0.30, valuation=0.35
            ),
        )
