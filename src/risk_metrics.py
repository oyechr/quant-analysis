"""
Risk Metrics Module

Calculates risk and performance metrics for stock analysis:
- Returns analysis (daily, cumulative, annualized)
- Volatility metrics (historical, downside deviation)
- Risk-adjusted returns (Sharpe, Sortino ratios)
- Drawdown analysis
- Market risk (Beta, Alpha)
- Tail risk (VaR, CVaR)
"""

import logging
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

from src.config import get_config

logger = logging.getLogger(__name__)


class RiskMetrics:
    """Calculate comprehensive risk and performance metrics"""

    def __init__(self):
        """Initialize with configuration"""
        self.config = get_config()

    def calculate_returns(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate return metrics

        Args:
            price_data: DataFrame with 'Close' prices and DatetimeIndex

        Returns:
            Dictionary with daily, cumulative, and annualized returns
        """
        if price_data is None or price_data.empty:
            logger.warning("Empty price data provided to calculate_returns")
            return {}

        if "Close" not in price_data.columns:
            logger.error("Price data missing 'Close' column")
            return {}

        try:
            # Daily returns
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty:
                logger.warning("Insufficient data to calculate returns")
                return {}

            # Cumulative returns
            prod_result = (1 + daily_returns).prod()
            # Convert to Python native float
            if isinstance(prod_result, (int, float, np.number)):
                cumulative_return = float(prod_result) - 1.0
            else:
                cumulative_return = 0.0

            # Annualized return (assume 252 trading days)
            trading_days = len(daily_returns)
            years = trading_days / 252
            annualized_return = float((1 + cumulative_return) ** (1 / years) - 1) if years > 0 else 0.0

            # Return statistics
            return {
                "daily_mean": float(daily_returns.mean()),
                "daily_std": float(daily_returns.std()),
                "daily_min": float(daily_returns.min()),
                "daily_max": float(daily_returns.max()),
                "cumulative_return": cumulative_return,
                "annualized_return": annualized_return,
                "total_trading_days": int(trading_days),
                "positive_days": int((daily_returns > 0).sum()),
                "negative_days": int((daily_returns < 0).sum()),
                "win_rate": float((daily_returns > 0).sum() / len(daily_returns)),
            }

        except Exception as e:
            logger.error(f"Error calculating returns: {e}")
            return {}

    def calculate_volatility(
        self, price_data: pd.DataFrame, window: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calculate volatility metrics

        Args:
            price_data: DataFrame with 'Close' prices
            window: Rolling window for volatility (None for full period)

        Returns:
            Dictionary with volatility metrics
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for volatility calculation")
            return {}

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty:
                return {}

            # Annualized volatility (252 trading days)
            daily_vol = daily_returns.std()
            annualized_vol = daily_vol * np.sqrt(252)

            # Downside deviation (only negative returns)
            downside_returns = daily_returns[daily_returns < 0]
            downside_deviation = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0

            metrics = {
                "daily_volatility": float(daily_vol),
                "annualized_volatility": float(annualized_vol),
                "downside_deviation": float(downside_deviation),
            }

            # Rolling volatility if window specified
            if window and window > 0 and len(daily_returns) >= window:
                rolling_vol = daily_returns.rolling(window=window).std() * np.sqrt(252)
                metrics["rolling_volatility_current"] = float(rolling_vol.iloc[-1])
                metrics["rolling_volatility_mean"] = float(rolling_vol.mean())
                metrics["rolling_volatility_max"] = float(rolling_vol.max())

            return metrics

        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")
            return {}

    def calculate_sharpe_ratio(
        self, price_data: pd.DataFrame, risk_free_rate: Optional[float] = None
    ) -> float:
        """
        Calculate Sharpe Ratio (risk-adjusted return)

        Args:
            price_data: DataFrame with 'Close' prices
            risk_free_rate: Annual risk-free rate (uses config default if None)

        Returns:
            Sharpe ratio (annualized)
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for Sharpe ratio")
            return 0.0

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty or daily_returns.std() == 0:
                return 0.0

            # Use config risk-free rate if not specified
            rf_rate = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate

            # Convert annual risk-free rate to daily
            daily_rf = (1 + rf_rate / 100) ** (1 / 252) - 1

            # Excess returns
            excess_returns = daily_returns - daily_rf

            # Sharpe ratio (annualized)
            sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252)

            return float(sharpe)

        except Exception as e:
            logger.error(f"Error calculating Sharpe ratio: {e}")
            return 0.0

    def calculate_sortino_ratio(
        self, price_data: pd.DataFrame, risk_free_rate: Optional[float] = None
    ) -> float:
        """
        Calculate Sortino Ratio (downside risk-adjusted return)

        Args:
            price_data: DataFrame with 'Close' prices
            risk_free_rate: Annual risk-free rate (uses config default if None)

        Returns:
            Sortino ratio (annualized)
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for Sortino ratio")
            return 0.0

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty:
                return 0.0

            # Use config risk-free rate if not specified
            rf_rate = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate

            # Convert annual risk-free rate to daily
            daily_rf = (1 + rf_rate / 100) ** (1 / 252) - 1

            # Excess returns
            excess_returns = daily_returns - daily_rf

            # Downside deviation (only negative excess returns)
            downside_returns = excess_returns[excess_returns < 0]
            if len(downside_returns) == 0 or downside_returns.std() == 0:
                return 0.0

            downside_std = downside_returns.std()

            # Sortino ratio (annualized)
            sortino = (excess_returns.mean() / downside_std) * np.sqrt(252)

            return float(sortino)

        except Exception as e:
            logger.error(f"Error calculating Sortino ratio: {e}")
            return 0.0

    def calculate_all_metrics(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate all risk metrics

        Args:
            price_data: DataFrame with 'Close' prices and DatetimeIndex

        Returns:
            Dictionary with all risk and performance metrics
        """
        logger.info("Calculating risk metrics...")

        if price_data is None or price_data.empty:
            logger.warning("No price data provided for risk analysis")
            return {}

        try:
            metrics = {
                "returns": self.calculate_returns(price_data),
                "volatility": self.calculate_volatility(price_data),
                "sharpe_ratio": self.calculate_sharpe_ratio(price_data),
                "sortino_ratio": self.calculate_sortino_ratio(price_data),
            }

            logger.info("Risk metrics calculation complete")
            return metrics

        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return {}
