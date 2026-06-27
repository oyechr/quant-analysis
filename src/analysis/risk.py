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
    calculate_kelly_criterion,
    convert_annual_to_daily_rate,
    to_float,
    validate_price_data,
)
from ..utils.report import validate_dataframe
from ..utils.serialization import format_date

logger = logging.getLogger(__name__)


class RiskMetrics:
    """
    Calculate comprehensive risk and performance metrics

    Can be used statelessly (legacy) or statefully by passing price_data to __init__.
    When stateful, metrics are cached after first calculation.
    """

    def __init__(
        self,
        price_data: Optional[pd.DataFrame] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
    ):
        """
        Initialize risk metrics calculator

        Args:
            price_data: DataFrame with 'Close' prices and DatetimeIndex (optional)
            benchmark_data: Optional benchmark data for beta/alpha
        """
        self.config = get_config()
        self.price_data = price_data
        self.benchmark_data = benchmark_data
        self._cached_metrics: Optional[Dict[str, Any]] = None

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
                from ..data_fetcher import DataFetcher

                fetcher = DataFetcher()
                benchmark_ticker = self.config.benchmark_ticker

                # Infer approximate period from price_data length and use period=
                # so the cache filename stays stable (start/end shifts daily).
                days = (price_data.index[-1] - price_data.index[0]).days
                period = "2y" if days > 400 else "1y" if days > 180 else "6mo"

                benchmark_data = fetcher.fetch_ticker(
                    benchmark_ticker,
                    period=period,
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

    def calculate_distribution_stats(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate return distribution statistics beyond normal distribution assumptions

        Computes skewness, kurtosis, and Jarque-Bera normality test to characterize
        the true shape of the return distribution. Most stock returns are NOT normally
        distributed — they have fat tails and negative skew.

        Metrics:
        - Skewness: 0 = symmetric, negative = left tail (more crash risk),
                    positive = right tail (more upside potential)
        - Excess Kurtosis: 0 = normal, >0 = fat tails (more extreme events),
                          <0 = thin tails (fewer extremes)
        - Jarque-Bera: statistical test for normality (p < 0.05 = non-normal)

        Returns:
            Dictionary with distribution metrics and interpretation
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            return {}

        try:
            daily_returns = price_data["Close"].pct_change().dropna()

            if len(daily_returns) < 30:
                logger.warning("Insufficient data for distribution stats (need 30+ days)")
                return {}

            n = len(daily_returns)
            mean = float(daily_returns.mean())
            std = float(daily_returns.std())

            if std == 0:
                return {}

            # Skewness (Fisher's definition)
            skewness = float(daily_returns.skew())

            # Excess kurtosis (Fisher's: normal = 0, not Pearson where normal = 3)
            kurtosis = float(daily_returns.kurtosis())

            # Jarque-Bera test statistic: JB = (n/6) * (S^2 + (K^2)/4)
            jb_stat = (n / 6.0) * (skewness**2 + (kurtosis**2) / 4.0)
            # Under H0 (normality), JB ~ chi-squared(2)
            # Critical values: 5.99 (5%), 9.21 (1%)
            is_normal = jb_stat < 5.99

            # Percentile analysis (empirical quantiles vs normal)
            p1 = float(np.percentile(daily_returns, 1))
            p5 = float(np.percentile(daily_returns, 5))
            p95 = float(np.percentile(daily_returns, 95))
            p99 = float(np.percentile(daily_returns, 99))

            # Expected percentiles under normal distribution
            from scipy.stats import norm  # type: ignore[import-not-found]

            normal_p1 = mean + norm.ppf(0.01) * std
            normal_p5 = mean + norm.ppf(0.05) * std
            normal_p95 = mean + norm.ppf(0.95) * std
            normal_p99 = mean + norm.ppf(0.99) * std

            tail_risk_ratio = abs(p1) / abs(normal_p1) if normal_p1 != 0 else 1.0

            # Interpretation
            skew_interpretation = (
                "negative (more crash risk)"
                if skewness < -0.5
                else "positive (more upside potential)"
                if skewness > 0.5
                else "approximately symmetric"
            )

            kurtosis_interpretation = (
                "fat tails (more extreme events than normal)"
                if kurtosis > 1.0
                else "thin tails (fewer extremes)"
                if kurtosis < -0.5
                else "approximately normal tails"
            )

            return {
                "skewness": skewness,
                "skew_interpretation": skew_interpretation,
                "excess_kurtosis": kurtosis,
                "kurtosis_interpretation": kurtosis_interpretation,
                "jarque_bera_statistic": jb_stat,
                "is_normally_distributed": is_normal,
                "tail_risk_ratio": tail_risk_ratio,
                "percentiles": {
                    "p1_actual": p1,
                    "p1_normal": float(normal_p1),
                    "p5_actual": p5,
                    "p5_normal": float(normal_p5),
                    "p95_actual": p95,
                    "p95_normal": float(normal_p95),
                    "p99_actual": p99,
                    "p99_normal": float(normal_p99),
                },
                "sample_size": n,
            }

        except ImportError:
            # scipy not available - compute without normal comparison
            daily_returns = price_data["Close"].pct_change().dropna()
            skewness = float(daily_returns.skew())
            kurtosis = float(daily_returns.kurtosis())
            n = len(daily_returns)
            jb_stat = (n / 6.0) * (skewness**2 + (kurtosis**2) / 4.0)

            skew_interpretation = (
                "negative (more crash risk)"
                if skewness < -0.5
                else "positive (more upside potential)"
                if skewness > 0.5
                else "approximately symmetric"
            )
            kurtosis_interpretation = (
                "fat tails (more extreme events than normal)"
                if kurtosis > 1.0
                else "thin tails (fewer extremes)"
                if kurtosis < -0.5
                else "approximately normal tails"
            )

            return {
                "skewness": skewness,
                "skew_interpretation": skew_interpretation,
                "excess_kurtosis": kurtosis,
                "kurtosis_interpretation": kurtosis_interpretation,
                "jarque_bera_statistic": jb_stat,
                "is_normally_distributed": jb_stat < 5.99,
                "sample_size": n,
            }
        except Exception as e:
            logger.error(f"Error calculating distribution stats: {e}")
            return {}

    def calculate_regime(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Detect current market regime using volatility and trend signals

        Classifies into 4 regimes:
        - Bull: Low volatility + Uptrend (SMA200 rising, price above)
        - Recovery: High volatility + Uptrend (volatile but trending up)
        - Distribution: Low volatility + Downtrend (quiet decline)
        - Bear: High volatility + Downtrend (panic selling)

        Uses 60-day rolling volatility percentile and 200-day MA slope.

        Returns:
            Dictionary with regime classification and supporting metrics
        """
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            return {}

        try:
            prices = price_data["Close"]

            if len(prices) < 60:
                return {}

            daily_returns = prices.pct_change().dropna()

            # Current 20-day rolling volatility (annualized)
            rolling_vol = daily_returns.rolling(window=20).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
            current_vol = to_float(rolling_vol.iloc[-1])

            # Volatility percentile (where does current vol rank in last 252 days?)
            lookback = min(252, len(rolling_vol))
            vol_window = rolling_vol.iloc[-lookback:]
            vol_percentile = float((vol_window < current_vol).sum() / len(vol_window) * 100)

            # Trend: price vs SMA50 and slope of SMA50
            sma_period = min(50, len(prices) - 1)
            sma = prices.rolling(window=sma_period).mean()
            price_above_sma = float(prices.iloc[-1]) > float(sma.iloc[-1])

            # SMA slope (annualized % change over last 20 days)
            if len(sma.dropna()) >= 20:
                sma_slope = (float(sma.iloc[-1]) - float(sma.iloc[-20])) / float(sma.iloc[-20])
            else:
                sma_slope = 0.0

            uptrend = price_above_sma and sma_slope > 0
            high_vol = vol_percentile > 60  # Above 60th percentile = high vol

            # Regime classification
            if uptrend and not high_vol:
                regime = "bull"
                description = "Low volatility uptrend - favorable conditions"
            elif uptrend and high_vol:
                regime = "recovery"
                description = "High volatility uptrend - volatile but improving"
            elif not uptrend and not high_vol:
                regime = "distribution"
                description = "Low volatility downtrend - quiet deterioration"
            else:
                regime = "bear"
                description = "High volatility downtrend - elevated risk"

            return {
                "regime": regime,
                "description": description,
                "volatility_percentile": vol_percentile,
                "current_annualized_vol": current_vol,
                "price_above_sma50": price_above_sma,
                "sma50_slope_pct": sma_slope * 100,
                "is_uptrend": uptrend,
                "is_high_volatility": high_vol,
            }

        except Exception as e:
            logger.error(f"Error calculating regime: {e}")
            return {}

    def calculate_all_metrics(
        self,
        price_data: Optional[pd.DataFrame] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Calculate all risk metrics

        Args:
            price_data: DataFrame with 'Close' prices and DatetimeIndex.
                        If None, uses self.price_data from __init__.
            benchmark_data: Optional benchmark data for beta/alpha (fetches if None).
                           If None, uses self.benchmark_data from __init__.

        Returns:
            Dictionary with all risk and performance metrics
        """
        # Use instance data if not provided
        price_data = price_data if price_data is not None else self.price_data
        benchmark_data = benchmark_data if benchmark_data is not None else self.benchmark_data

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
                "distribution": self.calculate_distribution_stats(price_data),
                "regime": self.calculate_regime(price_data),
                "kelly_criterion": calculate_kelly_criterion(price_data),
            }

            self._cached_metrics = metrics
            logger.info("Risk metrics calculation complete")
            return metrics

        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return {}

    def format_markdown(
        self, ticker: str = "", metrics: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Format risk analysis as detailed markdown report.

        Written for an intelligent reader who may not have finance background.

        Args:
            ticker: Stock ticker symbol for the report header
            metrics: Pre-computed metrics dict. If None, uses cached metrics.

        Returns:
            List of markdown lines
        """
        if metrics is None:
            metrics = self._cached_metrics or {}

        if not metrics:
            return ["*Risk analysis not available*"]

        md: List[str] = []

        # Market Regime (context-setting — put first)
        if "regime" in metrics and metrics["regime"]:
            regime = metrics["regime"]
            regime_name = regime.get("regime", "unknown").upper()
            md.append(f"## Current Market Regime: {regime_name}")
            md.append("")
            md.append(f"> {regime.get('description', '')}")
            md.append("")
            md.append(
                f"- Volatility is in the **{regime.get('volatility_percentile', 0):.0f}th percentile** of the past year"
            )
            md.append(
                f"- Price is **{'above' if regime.get('price_above_sma50') else 'below'}** its 50-day average"
            )
            md.append("")

        # Performance Summary
        md.append("## Performance")
        md.append("")
        if "returns" in metrics and metrics["returns"]:
            returns = metrics["returns"]
            cum_ret = returns.get("cumulative_return", 0)
            ann_ret = returns.get("annualized_return", 0)
            win_rate = returns.get("win_rate", 0)
            md.append(
                f"Over the analyzed period, this stock returned **{cum_ret:.1%}** total "
                f"(**{ann_ret:.1%}** annualized)."
            )
            md.append("")
            md.append(f"- **Win rate:** {win_rate:.0%} of trading days were positive")
            md.append(f"- **Best day:** {returns.get('daily_max', 0):.1%}")
            md.append(f"- **Worst day:** {returns.get('daily_min', 0):.1%}")
            md.append("")

        # Volatility & Risk (simplified)
        md.append("## Volatility")
        md.append("")
        md.append(
            "> *Volatility measures how much the price swings day-to-day. "
            "Higher volatility = bigger potential gains AND losses.*"
        )
        md.append("")
        if "volatility" in metrics and metrics["volatility"]:
            vol = metrics["volatility"]
            ann_vol = vol.get("annualized_volatility", 0)
            md.append(f"- **Annualized volatility:** {ann_vol:.0%}")
            if ann_vol > 0.50:
                md.append("  - Very high — expect large daily swings")
            elif ann_vol > 0.30:
                md.append("  - Elevated — noticeably more volatile than most stocks")
            elif ann_vol > 0.15:
                md.append("  - Moderate — typical for growth stocks")
            else:
                md.append("  - Low — relatively stable price movement")
            md.append(f"- **Downside deviation:** {vol.get('downside_deviation', 0):.0%}")
            md.append("  - *(Focuses only on negative moves — more relevant for risk)*")
            md.append("")

        # Risk-Adjusted Returns (explain what they mean)
        md.append("## Risk-Adjusted Returns")
        md.append("")
        md.append(
            '> *These ratios answer: "How much return did I get per unit of risk taken?" '
            "Higher is better.*"
        )
        md.append("")

        sharpe = metrics.get("sharpe_ratio", 0)
        sortino = metrics.get("sortino_ratio", 0)
        calmar = metrics.get("calmar_ratio", 0)

        md.append("| Metric | Value | What it means |")
        md.append("|--------|-------|---------------|")

        sharpe_comment = (
            "Excellent"
            if sharpe > 2
            else "Good"
            if sharpe > 1
            else "Acceptable"
            if sharpe > 0.5
            else "Poor"
            if sharpe > 0
            else "Negative — losing vs. cash"
        )
        md.append(f"| Sharpe Ratio | {sharpe:.2f} | {sharpe_comment} |")

        sortino_comment = (
            "Excellent"
            if sortino > 3
            else "Good"
            if sortino > 1.5
            else "Acceptable"
            if sortino > 0.5
            else "Poor"
        )
        md.append(
            f"| Sortino Ratio | {sortino:.2f} | {sortino_comment} (focuses on downside only) |"
        )

        calmar_comment = (
            "Excellent"
            if calmar > 3
            else "Good"
            if calmar > 1
            else "Concerning"
            if calmar > 0
            else "Negative return"
        )
        md.append(f"| Calmar Ratio | {calmar:.2f} | {calmar_comment} (return ÷ max loss) |")
        md.append("")

        # Drawdown (the big one for non-pros)
        md.append("## Drawdown (Peak-to-Trough Loss)")
        md.append("")
        md.append(
            "> *The maximum drawdown is the worst peak-to-valley decline. "
            "If you bought at the worst time, this is how much you would have lost.*"
        )
        md.append("")
        if "drawdown" in metrics and metrics["drawdown"]:
            dd = metrics["drawdown"]
            max_dd = dd.get("max_drawdown", 0)
            curr_dd = dd.get("current_drawdown", 0)
            md.append(f"- **Maximum drawdown:** {max_dd:.1%}")
            if dd.get("max_drawdown_date"):
                md.append(f"  - Occurred on {dd['max_drawdown_date']}")
            md.append(f"- **Current drawdown:** {curr_dd:.1%}")
            if dd.get("is_recovered"):
                md.append("  - Price has recovered to its peak")
            else:
                md.append(f"  - {dd.get('days_since_peak', 0)} days below peak and counting")
            if dd.get("recovery_days"):
                md.append(f"  - Previous recovery took {dd['recovery_days']} days")
            md.append("")

        # Market Risk
        md.append("## Market Risk (vs. S&P 500)")
        md.append("")
        if "market_risk" in metrics and metrics["market_risk"]:
            mr = metrics["market_risk"]
            beta = mr.get("beta", 0)
            alpha = mr.get("alpha", 0)
            corr = mr.get("correlation", 0)

            md.append(f"- **Beta: {beta:.2f}**")
            if beta > 2:
                md.append(f"  - Moves ~{beta:.1f}x as much as the market (very aggressive)")
            elif beta > 1:
                md.append(f"  - Moves ~{beta:.1f}x as much as the market (above average risk)")
            elif beta > 0.5:
                md.append("  - Moves roughly with the market")
            else:
                md.append("  - Low sensitivity to market moves")

            md.append(f"- **Alpha: {alpha:.1%}**")
            if alpha > 0:
                md.append("  - Outperforming what its risk level would predict")
            else:
                md.append("  - Underperforming what its risk level would predict")

            md.append(f"- **Correlation to market:** {corr:.0%}")
            if corr < 0.3:
                md.append("  - Low correlation — moves independently of the market")
            elif corr < 0.7:
                md.append("  - Moderate correlation — somewhat follows market direction")
            else:
                md.append("  - High correlation — closely tracks the market")
            md.append("")

        # Value at Risk (plain English)
        md.append("## Tail Risk (Extreme Scenarios)")
        md.append("")
        md.append('> *VaR answers: "What\'s my worst-case loss on a bad day?"*')
        md.append("")
        if "var_95" in metrics and metrics["var_95"]:
            var95 = metrics["var_95"]
            md.append(
                f"- **On a bad day (5% chance):** could lose **{abs(var95.get('var_historical', 0)):.1%}** or more"
            )
            md.append(
                f"- **On a very bad day (1% chance):** could lose **{abs(metrics.get('var_99', {}).get('var_historical', 0)):.1%}** or more"
            )
            md.append(
                f"- **Worst actual day:** {metrics.get('var_99', {}).get('worst_day', 0):.1%}"
            )
            md.append("")

        # Distribution Stats
        if "distribution" in metrics and metrics["distribution"]:
            dist = metrics["distribution"]
            md.append("## Return Distribution Shape")
            md.append("")
            md.append(
                '> *Stock returns often don\'t follow a "normal" bell curve. '
                "Understanding the actual shape helps assess true risk.*"
            )
            md.append("")

            skew = dist.get("skewness", 0)
            kurt = dist.get("excess_kurtosis", 0)
            is_normal = dist.get("is_normally_distributed", True)

            md.append(f"- **Skewness:** {skew:.2f} — {dist.get('skew_interpretation', '')}")
            md.append(f"- **Kurtosis:** {kurt:.2f} — {dist.get('kurtosis_interpretation', '')}")
            md.append(f"- **Normal distribution?** {'Yes' if is_normal else 'No'}")
            if not is_normal:
                md.append(
                    "  - Standard risk models (that assume normality) may understate true risk"
                )
            tail_ratio = dist.get("tail_risk_ratio")
            if tail_ratio and tail_ratio > 1.5:
                md.append(
                    f"  - Actual extreme losses are **{tail_ratio:.1f}x worse** than a normal model predicts"
                )
            md.append("")

        # Kelly Criterion (Position Sizing)
        if "kelly_criterion" in metrics and metrics["kelly_criterion"]:
            kelly = metrics["kelly_criterion"]
            md.append("## Position Sizing (Kelly Criterion)")
            md.append("")
            md.append(
                "> *The Kelly Criterion calculates the mathematically optimal position size "
                "based on your historical win rate and payoff ratio. Half-Kelly is the "
                "practical recommendation (less aggressive).*"
            )
            md.append("")
            md.append(f"- **Win rate:** {kelly.get('win_rate', 0):.0%} of days are positive")
            md.append(
                f"- **Payoff ratio:** {kelly.get('payoff_ratio', 0):.2f}x (avg win ÷ avg loss)"
            )
            md.append(f"- **Full Kelly:** {kelly.get('kelly_pct', 0):.1f}% of portfolio")
            md.append(
                f"- **Half-Kelly (recommended):** {kelly.get('half_kelly_pct', 0):.1f}% of portfolio"
            )
            md.append(f"- **Assessment:** {kelly.get('description', '')}")
            md.append("")

        return md
