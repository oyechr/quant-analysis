"""
Configuration Module
Centralized configuration for analysis parameters
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AnalysisConfig:
    """
    Configuration for quantitative analysis

    Provides centralized, type-safe configuration for:
    - Risk metrics parameters
    - Technical analysis thresholds
    - Fundamental analysis scoring criteria
    - Data fetching defaults
    """

    # ==================== Risk Parameters ====================
    risk_free_rate: float = 0.04  # 4% annual
    benchmark_ticker: str = "^GSPC"  # S&P 500 index

    # ==================== Technical Analysis ====================
    # Moving averages
    sma_periods: Optional[List[int]] = None  # Will default to [20, 50, 200]
    ema_short: int = 12
    ema_long: int = 26

    # Momentum indicators
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0

    stochastic_k_period: int = 14
    stochastic_d_period: int = 3
    stochastic_overbought: float = 80.0
    stochastic_oversold: float = 20.0

    # Volatility
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    atr_period: int = 14

    # ==================== Fundamental Analysis ====================
    # Quality score thresholds
    min_f_score_strong: int = 8  # Piotroski F-Score >= 8 = Strong
    min_f_score_average: int = 5  # 5-7 = Average

    z_score_safe: float = 2.99  # Altman Z-Score > 2.99 = Safe
    z_score_distress: float = 1.81  # < 1.81 = Distress zone

    # Growth expectations
    revenue_growth_strong: float = 15.0  # >15% CAGR = strong growth
    fcf_yield_attractive: float = 5.0  # >5% FCF yield = attractive

    # ==================== Data Fetching ====================
    default_period: str = "1y"
    default_interval: str = "1d"
    cache_enabled: bool = True

    # Validation sets
    valid_periods: Optional[set] = None
    valid_intervals: Optional[set] = None

    def __post_init__(self):
        """Initialize default values for mutable fields"""
        if self.sma_periods is None:
            self.sma_periods = [20, 50, 200]

        if self.valid_periods is None:
            self.valid_periods = {
                "1d",
                "5d",
                "1mo",
                "3mo",
                "6mo",
                "1y",
                "2y",
                "5y",
                "10y",
                "ytd",
                "max",
            }

        if self.valid_intervals is None:
            self.valid_intervals = {
                "1m",
                "2m",
                "5m",
                "15m",
                "30m",
                "60m",
                "90m",
                "1h",
                "1d",
                "5d",
                "1wk",
                "1mo",
                "3mo",
            }

    @classmethod
    def load_from_file(cls, path: Path) -> "AnalysisConfig":
        """
        Load configuration from JSON file

        Args:
            path: Path to config file

        Returns:
            AnalysisConfig instance with loaded values
        """
        if not path.exists():
            logger.info(f"Config file not found at {path}, using defaults")
            return cls()

        try:
            with open(path, "r") as f:
                data = json.load(f)

            logger.info(f"Loaded configuration from {path}")
            return cls(**data)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file {path}: {e}")
            logger.info("Using default configuration")
            return cls()
        except Exception as e:
            logger.error(f"Error loading config from {path}: {e}")
            logger.info("Using default configuration")
            return cls()

    def save_to_file(self, path: Path):
        """
        Save configuration to JSON file

        Args:
            path: Path where config should be saved
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            # Convert to dict, excluding non-serializable fields
            data = asdict(self)
            # Convert sets to lists for JSON serialization
            data["valid_periods"] = list(data["valid_periods"])
            data["valid_intervals"] = list(data["valid_intervals"])

            with open(path, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Configuration saved to {path}")

        except PermissionError:
            logger.error(f"Permission denied writing config to {path}")
            raise
        except OSError as e:
            logger.error(f"OS error saving config to {path}: {e}")
            raise

    def validate_period(self, period: str) -> bool:
        """Check if period is valid"""
        if self.valid_periods is None:
            return False
        return period in self.valid_periods

    def validate_interval(self, interval: str) -> bool:
        """Check if interval is valid"""
        if self.valid_intervals is None:
            return False
        return interval in self.valid_intervals


# Global default configuration instance
_default_config: Optional[AnalysisConfig] = None


def get_config() -> AnalysisConfig:
    """
    Get the global configuration instance

    Returns:
        Global AnalysisConfig instance
    """
    global _default_config
    if _default_config is None:
        # Try to load from default location
        config_path = Path("config.json")
        _default_config = AnalysisConfig.load_from_file(config_path)
    return _default_config


def set_config(config: AnalysisConfig):
    """
    Set the global configuration instance

    Args:
        config: AnalysisConfig instance to use globally
    """
    global _default_config
    _default_config = config
