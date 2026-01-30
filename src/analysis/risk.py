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
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import get_config
from ..utils.financial import (
    TRADING_DAYS_PER_YEAR,
    annualize_volatility,
    calculate_daily_returns,
    convert_annual_to_daily_rate,
    to_float,
    validate_price_data,
)
from ..utils.report import log_calculation_error, validate_dataframe
from ..utils.serialization import format_date

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
        if not validate_price_data(price_data):
            logger.warning("Empty or invalid price data provided to calculate_returns")
            return {}

        try:
            # Daily returns
            daily_returns = calculate_daily_returns(price_data)

            if daily_returns.empty:
                logger.warning("Insufficient data to calculate returns")
                return {}

            # Cumulative returns
            prod_result = (1 + daily_returns).prod()
            cumulative_return = to_float(prod_result) - 1.0

            # Annualized return
            trading_days = len(daily_returns)
            years = trading_days / TRADING_DAYS_PER_YEAR
            annualized_return = (
                float((1 + cumulative_return) ** (1 / years) - 1) if years > 0 else 0.0
            )

            # Return statistics
            return {
                "daily_mean": to_float(daily_returns.mean()),
                "daily_std": to_float(daily_returns.std()),
                "daily_min": to_float(daily_returns.min()),
                "daily_max": to_float(daily_returns.max()),
                "cumulative_return": cumulative_return,
                "annualized_return": annualized_return,
                "total_trading_days": int(trading_days),
                "positive_days": int((daily_returns > 0).sum()),
                "negative_days": int((daily_returns < 0).sum()),
                "win_rate": to_float((daily_returns > 0).sum() / len(daily_returns)),
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
        if not validate_dataframe(price_data, required_columns=["Close"]):
            logger.warning("Invalid price data for volatility calculation")
            return {}

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty:
                return {}

            # Annualized volatility (252 trading days)
            daily_vol = daily_returns.std()
            annualized_vol = annualize_volatility(to_float(daily_vol))

            # Downside deviation (only negative returns)
            downside_returns = daily_returns[daily_returns < 0]
            downside_deviation = (
                annualize_volatility(to_float(downside_returns.std()))
                if len(downside_returns) > 0
                else 0.0
            )

            metrics = {
                "daily_volatility": float(daily_vol),
                "annualized_volatility": float(annualized_vol),
                "downside_deviation": float(downside_deviation),
            }

            # Rolling volatility if window specified
            if window and window > 0 and len(daily_returns) >= window:
                rolling_vol = daily_returns.rolling(window=window).std() * np.sqrt(
                    TRADING_DAYS_PER_YEAR
                )
                metrics["rolling_volatility_current"] = to_float(rolling_vol.iloc[-1])
                metrics["rolling_volatility_mean"] = to_float(rolling_vol.mean())
                metrics["rolling_volatility_max"] = to_float(rolling_vol.max())

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
        if not validate_dataframe(price_data, required_columns=["Close"]):
            logger.warning("Invalid price data for Sharpe ratio")
            return 0.0

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty or daily_returns.std() == 0:
                return 0.0

            # Use config risk-free rate if not specified
            rf_rate = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate

            # Convert annual risk-free rate to daily
            daily_rf = convert_annual_to_daily_rate(rf_rate)

            # Excess returns
            excess_returns = daily_returns - daily_rf

            # Sharpe ratio (annualized)
            sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR)

            return to_float(sharpe)

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
        if not validate_dataframe(price_data, required_columns=["Close"]):
            logger.warning("Invalid price data for Sortino ratio")
            return 0.0

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty:
                return 0.0

            # Use config risk-free rate if not specified
            rf_rate = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate

            # Convert annual risk-free rate to daily
            daily_rf = convert_annual_to_daily_rate(rf_rate)

            # Excess returns
            excess_returns = daily_returns - daily_rf

            # Downside deviation (only negative excess returns)
            downside_returns = excess_returns[excess_returns < 0]
            if len(downside_returns) == 0 or downside_returns.std() == 0:
                return 0.0

            downside_std = downside_returns.std()

            # Sortino ratio (annualized)
            sortino = (excess_returns.mean() / downside_std) * np.sqrt(TRADING_DAYS_PER_YEAR)

            return to_float(sortino)

        except Exception as e:
            logger.error(f"Error calculating Sortino ratio: {e}")
            return 0.0

    def calculate_drawdown(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate drawdown metrics

        Args:
            price_data: DataFrame with 'Close' prices

        Returns:
            Dictionary with maximum drawdown, current drawdown, recovery time
        """
        if not validate_dataframe(price_data, required_columns=["Close"]):
            logger.warning("Invalid price data for drawdown calculation")
            return {}

        try:
            prices = price_data["Close"]

            # Running maximum (peak)
            running_max = prices.expanding().max()

            # Drawdown from peak
            drawdown = (prices - running_max) / running_max

            # Maximum drawdown
            max_drawdown = float(drawdown.min())
            max_dd_date = format_date(drawdown.idxmin(), "iso") if not drawdown.empty else None

            # Current drawdown
            current_drawdown = float(drawdown.iloc[-1])

            # Days since peak
            days_since_peak = 0
            for i in range(len(prices) - 1, -1, -1):
                if prices.iloc[i] >= running_max.iloc[i]:
                    break
                days_since_peak += 1

            # Recovery analysis (time from max drawdown to recovery)
            recovery_days = None
            if max_dd_date:
                max_dd_idx = drawdown.idxmin()
                # Find when price recovered to pre-drawdown peak
                peak_before_dd = running_max.loc[:max_dd_idx].iloc[-1]
                prices_after = prices.loc[max_dd_idx:]
                recovery_idx = prices_after[prices_after >= peak_before_dd].first_valid_index()
                if recovery_idx is not None:
                    recovery_days = int((recovery_idx - max_dd_idx).days)

            return {
                "max_drawdown": max_drawdown,
                "max_drawdown_date": max_dd_date,
                "current_drawdown": current_drawdown,
                "days_since_peak": days_since_peak,
                "recovery_days": recovery_days,
                "is_recovered": current_drawdown >= -0.001,  # Within 0.1% of peak
            }

        except Exception as e:
            logger.error(f"Error calculating drawdown: {e}")
            return {}

    def calculate_beta_alpha(
        self, price_data: pd.DataFrame, benchmark_data: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Calculate Beta and Alpha vs benchmark

        Args:
            price_data: DataFrame with 'Close' prices
            benchmark_data: DataFrame with benchmark 'Close' prices (fetches if None)

        Returns:
            Dictionary with beta, alpha, correlation
        """
        if not validate_dataframe(price_data, required_columns=["Close"]):
            logger.warning("Invalid price data for beta/alpha calculation")
            return {}

        try:
            # Fetch benchmark data if not provided
            if benchmark_data is None or benchmark_data.empty:
                from src.data_fetcher import DataFetcher

                fetcher = DataFetcher()
                benchmark_ticker = self.config.benchmark_ticker

                # Match period with price_data
                start_date = price_data.index[0]
                end_date = price_data.index[-1]

                benchmark_data = fetcher.fetch_ticker(
                    benchmark_ticker,
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                )

                if benchmark_data is None or benchmark_data.empty:
                    logger.warning(f"Could not fetch benchmark data for {benchmark_ticker}")
                    return {}

            # Calculate returns
            stock_returns = price_data["Close"].pct_change().dropna()
            benchmark_returns = benchmark_data["Close"].pct_change().dropna()

            # Align dates
            aligned = pd.DataFrame(
                {"stock": stock_returns, "benchmark": benchmark_returns}
            ).dropna()

            if aligned.empty or len(aligned) < 2:
                logger.warning("Insufficient overlapping data for beta/alpha")
                return {}

            # Beta (covariance / variance)
            covariance = float(aligned["stock"].cov(aligned["benchmark"]))
            bm_var_result = aligned["benchmark"].var()
            benchmark_variance = (
                float(bm_var_result) if isinstance(bm_var_result, (int, float, np.number)) else 0.0
            )
            beta = covariance / benchmark_variance if benchmark_variance != 0 else 0.0

            # Alpha (annualized)
            stock_mean_return = float(aligned["stock"].mean()) * TRADING_DAYS_PER_YEAR
            benchmark_mean_return = float(aligned["benchmark"].mean()) * TRADING_DAYS_PER_YEAR
            rf_rate = self.config.risk_free_rate / 100

            alpha = stock_mean_return - (rf_rate + beta * (benchmark_mean_return - rf_rate))

            # Correlation
            correlation = float(aligned["stock"].corr(aligned["benchmark"]))

            # R-squared
            r_squared = correlation**2

            return {
                "beta": beta,
                "alpha": float(alpha),
                "correlation": correlation,
                "r_squared": r_squared,
                "benchmark": self.config.benchmark_ticker,
            }

        except Exception as e:
            logger.error(f"Error calculating beta/alpha: {e}")
            return {}

    def calculate_var(
        self, price_data: pd.DataFrame, confidence_level: float = 0.95
    ) -> Dict[str, Any]:
        """
        Calculate Value at Risk (VaR) and Conditional VaR (CVaR)

        Args:
            price_data: DataFrame with 'Close' prices
            confidence_level: Confidence level (default 0.95 for 95%)

        Returns:
            Dictionary with VaR and CVaR at specified confidence level
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for VaR calculation")
            return {}

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if daily_returns.empty:
                return {}

            # Historical VaR (percentile of returns)
            var = float(np.percentile(daily_returns, (1 - confidence_level) * 100))

            # CVaR (expected shortfall - mean of returns below VaR)
            returns_below_var = daily_returns[daily_returns <= var]
            cvar = float(returns_below_var.mean()) if len(returns_below_var) > 0 else var

            # Parametric VaR (assumes normal distribution)
            mean_return = float(daily_returns.mean())
            std_return = float(daily_returns.std())
            z_score = np.abs(
                np.percentile(np.random.standard_normal(10000), (1 - confidence_level) * 100)
            )
            parametric_var = mean_return - z_score * std_return

            return {
                "confidence_level": confidence_level,
                "var_historical": var,
                "cvar_historical": cvar,
                "var_parametric": parametric_var,
                "worst_day": float(daily_returns.min()),
            }

        except Exception as e:
            logger.error(f"Error calculating VaR: {e}")
            return {}

    def calculate_information_ratio(
        self, price_data: pd.DataFrame, benchmark_data: Optional[pd.DataFrame] = None
    ) -> float:
        """
        Calculate Information Ratio (active return / tracking error)

        Measures risk-adjusted excess return vs benchmark. Higher is better.
        IR > 0.5 is good, IR > 1.0 is excellent.

        Args:
            price_data: DataFrame with 'Close' prices
            benchmark_data: DataFrame with benchmark 'Close' prices (fetches if None)

        Returns:
            Information ratio
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for Information Ratio")
            return 0.0

        try:
            # Fetch benchmark if not provided
            if benchmark_data is None or benchmark_data.empty:
                from .data_fetcher import DataFetcher

                fetcher = DataFetcher()
                start_date = price_data.index.min()
                end_date = price_data.index.max()
                benchmark_data = fetcher.fetch_ticker(
                    self.config.benchmark_ticker,
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                )

            if benchmark_data is None or benchmark_data.empty:
                logger.warning("Benchmark data not available for Information Ratio")
                return 0.0

            # Calculate daily returns
            stock_returns = price_data["Close"].pct_change().dropna()
            benchmark_returns = benchmark_data["Close"].pct_change().dropna()

            # Align data
            aligned = pd.DataFrame(
                {"stock": stock_returns, "benchmark": benchmark_returns}
            ).dropna()

            if aligned.empty or len(aligned) < 2:
                return 0.0

            # Active returns (excess return over benchmark)
            active_returns = aligned["stock"] - aligned["benchmark"]

            # Tracking error (volatility of active returns)
            tracking_error = active_returns.std()

            if tracking_error == 0:
                return 0.0

            # Information Ratio (annualized)
            mean_active_return = active_returns.mean()
            information_ratio = (mean_active_return / tracking_error) * np.sqrt(
                TRADING_DAYS_PER_YEAR
            )

            return to_float(information_ratio)

        except Exception as e:
            logger.error(f"Error calculating Information Ratio: {e}")
            return 0.0

    def calculate_calmar_ratio(self, price_data: pd.DataFrame) -> float:
        """
        Calculate Calmar Ratio (annualized return / max drawdown)

        Measures return per unit of downside risk. Higher is better.
        Calmar > 1.0 is good, > 3.0 is excellent.

        Args:
            price_data: DataFrame with 'Close' prices

        Returns:
            Calmar ratio
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for Calmar Ratio")
            return 0.0

        try:
            # Get annualized return
            returns_metrics = self.calculate_returns(price_data)
            annualized_return = returns_metrics.get("annualized_return", 0.0)

            # Get max drawdown
            drawdown_metrics = self.calculate_drawdown(price_data)
            max_drawdown = abs(drawdown_metrics.get("max_drawdown", 0.0))

            if max_drawdown == 0:
                return 0.0

            calmar = annualized_return / max_drawdown

            return float(calmar)

        except Exception as e:
            logger.error(f"Error calculating Calmar Ratio: {e}")
            return 0.0

    def calculate_rolling_ratios(
        self, price_data: pd.DataFrame, windows: List[int] = [30, 60, 90]
    ) -> Dict[str, Any]:
        """
        Calculate rolling Sharpe and Sortino ratios over different windows

        Args:
            price_data: DataFrame with 'Close' prices
            windows: List of rolling window sizes in days

        Returns:
            Dictionary with rolling ratio statistics for each window
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            logger.warning("Invalid price data for rolling ratios")
            return {}

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if len(daily_returns) < max(windows):
                logger.warning(f"Insufficient data for rolling ratios (need {max(windows)} days)")
                return {}

            # Daily risk-free rate
            rf_rate = self.config.risk_free_rate
            daily_rf = convert_annual_to_daily_rate(rf_rate)

            results = {}

            for window in windows:
                if len(daily_returns) < window:
                    continue

                # Rolling Sharpe
                excess_returns = daily_returns - daily_rf
                rolling_mean = excess_returns.rolling(window=window).mean()
                rolling_std = excess_returns.rolling(window=window).std()
                rolling_sharpe = (rolling_mean / rolling_std) * np.sqrt(TRADING_DAYS_PER_YEAR)

                # Rolling Sortino
                def calculate_downside_std(window_returns):
                    downside = window_returns[window_returns < 0]
                    return downside.std() if len(downside) > 0 else np.nan

                rolling_downside_std = excess_returns.rolling(window=window).apply(
                    calculate_downside_std, raw=False
                )
                rolling_sortino = (rolling_mean / rolling_downside_std) * np.sqrt(
                    TRADING_DAYS_PER_YEAR
                )

                # Drop NaN values
                rolling_sharpe = rolling_sharpe.dropna()
                rolling_sortino = rolling_sortino.dropna()

                if not rolling_sharpe.empty:
                    results[f"sharpe_{window}d"] = {
                        "current": to_float(rolling_sharpe.iloc[-1]),
                        "mean": to_float(rolling_sharpe.mean()),
                        "min": to_float(rolling_sharpe.min()),
                        "max": to_float(rolling_sharpe.max()),
                        "std": to_float(rolling_sharpe.std()),
                    }

                if not rolling_sortino.empty:
                    results[f"sortino_{window}d"] = {
                        "current": to_float(rolling_sortino.iloc[-1]),
                        "mean": to_float(rolling_sortino.mean()),
                        "min": to_float(rolling_sortino.min()),
                        "max": to_float(rolling_sortino.max()),
                        "std": to_float(rolling_sortino.std()),
                    }

            return results

        except Exception as e:
            logger.error(f"Error calculating rolling ratios: {e}")
            return {}

    def calculate_all_metrics(
        self, price_data: pd.DataFrame, benchmark_data: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Calculate all risk metrics

        Args:
            price_data: DataFrame with 'Close' prices and DatetimeIndex
            benchmark_data: Optional benchmark data for beta/alpha (fetches if None)

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
                "information_ratio": self.calculate_information_ratio(price_data, benchmark_data),
                "calmar_ratio": self.calculate_calmar_ratio(price_data),
                "drawdown": self.calculate_drawdown(price_data),
                "market_risk": self.calculate_beta_alpha(price_data, benchmark_data),
                "var_95": self.calculate_var(price_data, confidence_level=0.95),
                "var_99": self.calculate_var(price_data, confidence_level=0.99),
                "rolling_ratios": self.calculate_rolling_ratios(price_data),
            }

            logger.info("Risk metrics calculation complete")
            return metrics

        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return {}
