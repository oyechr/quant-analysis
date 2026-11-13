"""
Configuration Module
Centralized configuration for analysis parameters
"""

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_HOURS: dict[str, float] = {
    "prices": 12,  # daily bars; refresh after each session
    "info": 24,  # price-dependent ratios (P/E, market cap)
    "earnings": 72,
    "analyst_ratings": 72,
    "dividends": 168,
    "fundamentals": 168,  # statements change quarterly, refresh weekly around earnings
    "holders": 720,
    "universe": 720,  # index constituent lists
    "industry": 720,  # Yahoo industry peer lists
}

# A placeholder: SEC asks for a real name and contact (see Edgar13FSource)
DEFAULT_EDGAR_USER_AGENT = "PersonalResearch research@example.com"

CONFIG_FILE = "config.json"
# The checkout this package runs from (the folder holding src/)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Keys config.json can leave out: the provider's usual environment variable
# fills them in (config.json wins when both are set)
ENV_KEYS: dict[str, tuple[str, ...]] = {
    "llm_anthropic_api_key": ("ANTHROPIC_API_KEY",),
    "llm_openai_api_key": ("OPENAI_API_KEY",),
    "llm_google_api_key": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openfigi_api_key": ("OPENFIGI_API_KEY",),
}


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
    # Mature-market equity risk premium for CAPM (Damodaran's implied ERP has been
    # about 4-5% in recent years; Kroll recommends 5%)
    equity_risk_premium: float = 0.05
    benchmark_ticker: str = "^GSPC"  # S&P 500 index (default for US / unmapped exchanges)
    # Per-exchange benchmark overrides keyed by Yahoo suffix, e.g. {".OL": "OBX.OL"}.
    # Built-in defaults live in src/markets.py.
    benchmark_by_suffix: dict[str, str] = field(default_factory=dict)

    # ==================== Technical Analysis ====================
    # Moving averages
    sma_periods: list[int] | None = None  # Will default to [20, 50, 200]
    ema_short: int = 12
    ema_long: int = 26

    # Momentum indicators. Scoring thresholds (RSI bands, growth, FCF yield,
    # Altman zones) live in scoring.config and analysis.fundamental.altman_zones
    rsi_period: int = 14

    stochastic_k_period: int = 14
    stochastic_d_period: int = 3

    # Volatility
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    atr_period: int = 14

    # ==================== Fundamental Analysis ====================
    # Quality score thresholds
    min_f_score_strong: int = 8  # Piotroski F-Score >= 8 = Strong
    min_f_score_average: int = 5  # 5-7 = Average

    # ==================== Data Fetching ====================
    default_period: str = "1y"
    default_interval: str = "1d"
    cache_enabled: bool = True
    # Max cache age per resource, in hours. Older entries are refetched.
    # A value <= 0 disables expiry for that resource.
    cache_ttl_hours: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CACHE_TTL_HOURS))

    # ==================== LLM Integration ====================
    llm_model: str = "gemini-3.8-flash"  # free tier with llm_google_api_key
    # repr=False keeps keys out of logs and tracebacks that print the config
    llm_anthropic_api_key: str | None = field(default=None, repr=False)
    llm_openai_api_key: str | None = field(default=None, repr=False)
    llm_google_api_key: str | None = field(default=None, repr=False)  # AI Studio (Gemini)

    # ==================== Discovery / EDGAR ====================
    edgar_user_agent: str = DEFAULT_EDGAR_USER_AGENT
    # Optional (https://www.openfigi.com/api): CUSIP -> ticker lookups run
    # 100 per request instead of 10, at 10x the rate
    openfigi_api_key: str | None = field(default=None, repr=False)

    # Validation sets
    valid_periods: set[str] | None = None
    valid_intervals: set[str] | None = None

    def __post_init__(self) -> None:
        """Initialize default values for mutable fields"""
        if self.sma_periods is None:
            self.sma_periods = [20, 50, 200]

        # Partial overrides in config.json keep the defaults for unspecified resources
        self.cache_ttl_hours = {**DEFAULT_CACHE_TTL_HOURS, **(self.cache_ttl_hours or {})}

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
    def load_from_file(cls, path: Path) -> AnalysisConfig:
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
            with open(path) as f:
                data = json.load(f)

            # A removed or misspelled key would make cls(**data) fail and drop
            # the whole file to defaults: skip it, and say so
            known = {f.name for f in fields(cls)}
            unknown = sorted(set(data) - known)
            if unknown:
                logger.warning(f"Ignoring unknown config keys in {path}: {', '.join(unknown)}")
            logger.info(f"Loaded configuration from {path}")
            return cls(**{k: v for k, v in data.items() if k in known})

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file {path}: {e}")
            logger.info("Using default configuration")
            return cls()
        except Exception as e:
            logger.error(f"Error loading config from {path}: {e}")
            logger.info("Using default configuration")
            return cls()

    def save_to_file(self, path: Path) -> None:
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
_default_config: AnalysisConfig | None = None


def get_config() -> AnalysisConfig:
    """
    Get the global configuration instance

    Returns:
        Global AnalysisConfig instance
    """
    global _default_config
    if _default_config is None:
        config = AnalysisConfig.load_from_file(config_path())
        _default_config = with_env_keys(config, os.environ)
    return _default_config


def config_path() -> Path:
    """Where config.json is read from.

    $QUANT_CONFIG if set, else ./config.json, else the one in the checkout
    (so running from a subfolder doesn't silently drop the keys and TTLs).
    """
    override = os.environ.get("QUANT_CONFIG")
    if override:
        return Path(override)
    local = Path(CONFIG_FILE)
    if local.exists():
        return local
    return REPO_ROOT / CONFIG_FILE


def with_env_keys(config: AnalysisConfig, env: Mapping[str, str]) -> AnalysisConfig:
    """Fill keys config.json left out from their environment variables."""
    for name, variables in ENV_KEYS.items():
        if getattr(config, name):
            continue
        for var in variables:
            if env.get(var):
                setattr(config, name, env[var])
                logger.info(f"{name} taken from ${var}")
                break
    return config


def set_config(config: AnalysisConfig) -> None:
    """
    Set the global configuration instance

    Args:
        config: AnalysisConfig instance to use globally
    """
    global _default_config
    _default_config = config
