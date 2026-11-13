"""
Technical Analysis Module
Calculates technical indicators from price data using finta library
"""

import logging
import math
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from finta import TA

from ..config import AnalysisConfig, get_config
from ..utils.financial import trading_dates
from ..utils.report import get_currency_symbol
from ..utils.serialization import format_date

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """
    Calculates technical indicators from OHLCV price data

    Uses ta library for standard technical analysis indicators.
    Separates concerns: price data storage vs. indicator calculation.
    """

    def __init__(
        self,
        price_data: pd.DataFrame,
        currency: str = "USD",
        config: Optional[AnalysisConfig] = None,
    ):
        """
        Initialize analyzer with price data

        Args:
            price_data: DataFrame with OHLCV columns (Open, High, Low, Close, Volume)
                       Must have datetime index
            currency: ISO 4217 currency code (e.g., 'USD', 'NOK', 'CAD')
            config: Analysis configuration (uses global defaults if not provided)
        """

        # Validate required columns
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        missing = [col for col in required_cols if col not in price_data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        self.df = price_data.copy()
        self.currency = currency
        self.config = config or get_config()

    def _finta_df(self) -> pd.DataFrame:
        """Return a finta-compatible DataFrame with lowercase column names."""
        return self.df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

    # ==================== Trend Indicators ====================

    def calculate_moving_averages(
        self,
        sma_periods: Sequence[int] = (20, 50, 200),
        ema_periods: Sequence[int] = (12, 26),
    ) -> pd.DataFrame:
        """
        Calculate Simple and Exponential Moving Averages

        Args:
            sma_periods: Periods for SMA calculation
            ema_periods: Periods for EMA calculation

        Returns:
            DataFrame with SMA and EMA columns added
        """
        fdf = self._finta_df()
        for period in sma_periods:
            self.df[f"SMA_{period}"] = TA.SMA(fdf, period=period).values

        for period in ema_periods:
            self.df[f"EMA_{period}"] = TA.EMA(fdf, period=period).values

        return self.df

    def calculate_macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """
        Calculate MACD (Moving Average Convergence Divergence)

        Args:
            fast: Fast EMA period
            slow: Slow EMA period
            signal: Signal line period

        Returns:
            DataFrame with MACD, MACD_signal, MACD_diff columns
        """
        macd_df = TA.MACD(self._finta_df(), period_fast=fast, period_slow=slow, signal=signal)
        self.df["MACD"] = macd_df["MACD"].values
        self.df["MACD_signal"] = macd_df["SIGNAL"].values
        self.df["MACD_diff"] = (macd_df["MACD"] - macd_df["SIGNAL"]).values
        return self.df

    # ==================== Momentum Indicators ====================

    def calculate_rsi(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate RSI (Relative Strength Index)

        Args:
            period: Lookback period (typically 14)

        Returns:
            DataFrame with RSI column added
        """
        self.df["RSI"] = TA.RSI(self._finta_df(), period=period).values
        return self.df

    def calculate_stochastic(self, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        """
        Calculate Stochastic Oscillator

        Args:
            k_period: %K period
            d_period: %D period (signal line)

        Returns:
            DataFrame with Stochastic %K and %D columns
        """
        fdf = self._finta_df()
        self.df["Stoch_K"] = TA.STOCH(fdf, period=k_period).values
        self.df["Stoch_D"] = TA.STOCHD(fdf, period=d_period, stoch_period=k_period).values
        return self.df

    # ==================== Volatility Indicators ====================

    def calculate_bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        """
        Calculate Bollinger Bands

        Args:
            period: Moving average period
            std_dev: Number of standard deviations

        Returns:
            DataFrame with BB_lower, BB_middle, BB_upper columns
        """
        bb_df = TA.BBANDS(self._finta_df(), period=period, std_multiplier=std_dev)
        self.df["BB_upper"] = bb_df["BB_UPPER"].values
        self.df["BB_middle"] = bb_df["BB_MIDDLE"].values
        self.df["BB_lower"] = bb_df["BB_LOWER"].values
        return self.df

    def calculate_atr(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate ATR (Average True Range)

        Args:
            period: Lookback period

        Returns:
            DataFrame with ATR column added
        """
        self.df["ATR"] = TA.ATR(self._finta_df(), period=period).values
        return self.df

    def calculate_adx(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate ADX (Average Directional Index) - Trend Strength

        Args:
            period: Lookback period

        Returns:
            DataFrame with ADX column added
        """
        self.df["ADX"] = TA.ADX(self._finta_df(), period=period).values
        return self.df

    # ==================== Volume Indicators ====================

    def calculate_obv(self) -> pd.DataFrame:
        """
        Calculate OBV (On-Balance Volume)

        Returns:
            DataFrame with OBV column added
        """
        self.df["OBV"] = TA.OBV(self._finta_df()).values
        return self.df

    def calculate_vwap(self) -> pd.DataFrame:
        """
        Calculate VWAP (Volume Weighted Average Price)

        Returns:
            DataFrame with VWAP column added
        """
        self.df["VWAP"] = TA.VWAP(self._finta_df()).values
        return self.df

    def calculate_mfi(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate MFI (Money Flow Index) - Volume-weighted RSI

        Args:
            period: Lookback period

        Returns:
            DataFrame with MFI column added
        """
        self.df["MFI"] = TA.MFI(self._finta_df(), period=period).values
        return self.df

    def calculate_williams_r(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate Williams %R - Momentum Oscillator

        Args:
            period: Lookback period

        Returns:
            DataFrame with Williams %R column added
        """
        self.df["Williams_R"] = TA.WILLIAMS(self._finta_df(), period=period).values
        return self.df

    def calculate_statistics(self) -> Dict[str, Any]:
        """
        Calculate statistical summary of price and volume data

        Returns:
            Dictionary with statistical measures
        """
        if self.df.empty:
            return {}

        close_prices = self.df["Close"]
        volume = self.df["Volume"]

        # Calculate returns
        returns = close_prices.pct_change().dropna()

        # Price statistics
        current_price = float(close_prices.iloc[-1])
        max_price = float(close_prices.max())
        min_price = float(close_prices.min())
        mean_price = float(close_prices.mean())
        std_price = float(close_prices.std())

        # Period return
        start_price = float(close_prices.iloc[0])
        period_return = ((current_price - start_price) / start_price) * 100

        # Volatility (annualized from daily returns)
        daily_volatility = float(returns.std())
        annual_volatility = daily_volatility * (252**0.5) * 100  # 252 trading days

        # Volume statistics
        avg_volume = float(volume.mean())
        max_volume = float(volume.max())
        min_volume = float(volume.min())
        current_volume = float(volume.iloc[-1])

        # Find dates for extremes
        max_price_date = format_date(close_prices.idxmax())
        min_price_date = format_date(close_prices.idxmin())
        max_volume_date = format_date(volume.idxmax())

        return {
            "price": {
                "current": current_price,
                "high": max_price,
                "high_date": max_price_date,
                "low": min_price,
                "low_date": min_price_date,
                "mean": mean_price,
                "std_dev": std_price,
                "std_dev_pct": (std_price / mean_price) * 100 if mean_price > 0 else 0,
            },
            "returns": {
                "period_return_pct": period_return,
                "daily_volatility_pct": daily_volatility * 100,
                "annual_volatility_pct": annual_volatility,
            },
            "volume": {
                "current": current_volume,
                "average": avg_volume,
                "max": max_volume,
                "max_date": max_volume_date,
                "min": min_volume,
                "volume_vs_avg_pct": (
                    ((current_volume - avg_volume) / avg_volume) * 100 if avg_volume > 0 else 0
                ),
            },
        }

    # ==================== All-in-One Methods ====================

    def calculate_all_indicators(self) -> pd.DataFrame:
        """
        Calculate all standard technical indicators using config parameters

        Returns:
            DataFrame with all indicators added
        """
        logger.info("Calculating all technical indicators...")
        cfg = self.config

        # Trend indicators
        self.calculate_moving_averages(
            sma_periods=cfg.sma_periods or [20, 50, 200],
            ema_periods=[cfg.ema_short, cfg.ema_long],
        )
        self.calculate_macd()

        # Momentum indicators
        self.calculate_rsi(period=cfg.rsi_period)
        self.calculate_stochastic(
            k_period=cfg.stochastic_k_period, d_period=cfg.stochastic_d_period
        )
        self.calculate_williams_r()

        # Volatility indicators
        self.calculate_bollinger_bands(period=cfg.bollinger_period, std_dev=cfg.bollinger_std)
        self.calculate_atr(period=cfg.atr_period)
        self.calculate_adx()

        # Volume indicators
        self.calculate_obv()
        self.calculate_vwap()
        self.calculate_mfi()

        logger.info(f"Calculated {len(self.df.columns) - 6} indicators")  # Subtract OHLCV + 1
        return self.df

    def get_latest_values(self) -> Dict[str, Any]:
        """
        Get most recent indicator values (latest row)

        Returns:
            Dictionary with latest indicator values
        """
        if self.df.empty:
            return {}

        latest = self.df.iloc[-1]

        # Extract only indicator columns (exclude OHLCV)
        base_cols = ["Open", "High", "Low", "Close", "Volume", "Adj Close"]
        indicator_cols = [col for col in self.df.columns if col not in base_cols]

        result: Dict[str, Any] = {
            "date": format_date(latest.name),
            "close_price": float(latest["Close"]),
            "indicators": {},
        }

        for col in indicator_cols:
            value = latest[col]
            # Handle NaN values
            result["indicators"][col] = None if pd.isna(value) else float(value)

        return result

    def crossovers(self) -> Dict[str, Optional[str]]:
        """
        The trend state for scoring, as values rather than text:

        - `macd_cross`: "bullish" / "bearish" when MACD crossed its signal
          line on the last bar, else None (being above it is not a cross);
        - `ma_regime`: "bullish" when SMA 50 is above SMA 200, else "bearish";
        - `ma_cross`: "golden" / "death" when SMA 50 crossed SMA 200 on the
          last bar, else None.
        """
        state: Dict[str, Optional[str]] = {"macd_cross": None, "ma_regime": None, "ma_cross": None}
        if len(self.df) < 2:
            return state
        last, prev = self.df.iloc[-1], self.df.iloc[-2]

        def cross(fast: str, slow: str, up: str, down: str) -> Optional[str]:
            values = [_finite(row.get(name)) for row in (last, prev) for name in (fast, slow)]
            if not all(math.isfinite(v) for v in values):
                return None
            now, before = values[0] - values[1], values[2] - values[3]
            if before <= 0 < now:
                return up
            if before >= 0 > now:
                return down
            return None

        state["macd_cross"] = cross("MACD", "MACD_signal", "bullish", "bearish")
        state["ma_cross"] = cross("SMA_50", "SMA_200", "golden", "death")
        sma50, sma200 = last.get("SMA_50"), last.get("SMA_200")
        if sma50 is not None and sma200 is not None and not pd.isna(sma50) and not pd.isna(sma200):
            state["ma_regime"] = "bullish" if sma50 > sma200 else "bearish"
        return state

    def generate_signals(self) -> Dict[str, str]:
        """
        Generate trading signals based on indicator values

        Returns:
            Dictionary with signal interpretations
        """
        if self.df.empty or len(self.df) < 2:
            return {}

        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        signals = {}

        # RSI signals
        if "RSI" in self.df.columns and not pd.isna(latest["RSI"]):
            rsi = latest["RSI"]
            if rsi > 70:
                signals["RSI"] = "Overbought (>70) - potential sell signal"
            elif rsi < 30:
                signals["RSI"] = "Oversold (<30) - potential buy signal"
            else:
                signals["RSI"] = f"Neutral ({rsi:.1f})"

        # MACD signals
        if "MACD" in self.df.columns and "MACD_signal" in self.df.columns:
            macd = latest["MACD"]
            macd_signal = latest["MACD_signal"]
            prev_macd = prev["MACD"]
            prev_signal = prev["MACD_signal"]

            if not pd.isna(macd) and not pd.isna(macd_signal):
                # Bullish crossover
                if prev_macd < prev_signal and macd > macd_signal:
                    signals["MACD"] = "Bullish crossover - buy signal"
                # Bearish crossover
                elif prev_macd > prev_signal and macd < macd_signal:
                    signals["MACD"] = "Bearish crossover - sell signal"
                elif macd > macd_signal:
                    signals["MACD"] = "Bullish"
                else:
                    signals["MACD"] = "Bearish"

        # Moving average trend
        if "SMA_50" in self.df.columns and "SMA_200" in self.df.columns:
            sma50 = latest["SMA_50"]
            sma200 = latest["SMA_200"]
            close = latest["Close"]

            if not pd.isna(sma50) and not pd.isna(sma200):
                cross = self.crossovers()["ma_cross"]
                if cross == "golden":
                    signals["MA_Trend"] = "Golden Cross today (SMA 50 crossed above SMA 200)"
                elif cross == "death":
                    signals["MA_Trend"] = "Death Cross today (SMA 50 crossed below SMA 200)"
                elif sma50 > sma200:
                    signals["MA_Trend"] = "Bullish (SMA 50 above SMA 200)"
                else:
                    signals["MA_Trend"] = "Bearish (SMA 50 below SMA 200)"

                # Price vs MA
                if close > sma50 > sma200:
                    signals["Price_Position"] = "Strong uptrend (above both MAs)"
                elif close < sma50 < sma200:
                    signals["Price_Position"] = "Strong downtrend (below both MAs)"

        # Bollinger Bands
        if all(col in self.df.columns for col in ["BB_lower", "BB_middle", "BB_upper"]):
            bb_lower = latest["BB_lower"]
            bb_upper = latest["BB_upper"]
            close = latest["Close"]

            if not pd.isna(bb_lower) and not pd.isna(bb_upper):
                if close > bb_upper:
                    signals["Bollinger_Bands"] = "Price above upper band - overbought"
                elif close < bb_lower:
                    signals["Bollinger_Bands"] = "Price below lower band - oversold"
                else:
                    signals["Bollinger_Bands"] = "Price within bands - normal"

        # ADX - Trend Strength
        if "ADX" in self.df.columns and not pd.isna(latest["ADX"]):
            adx = latest["ADX"]
            if adx > 25:
                signals["ADX"] = f"Strong trend ({adx:.1f})"
            elif adx > 20:
                signals["ADX"] = f"Moderate trend ({adx:.1f})"
            else:
                signals["ADX"] = f"Weak/no trend ({adx:.1f})"

        # MFI - Money Flow
        if "MFI" in self.df.columns and not pd.isna(latest["MFI"]):
            mfi = latest["MFI"]
            if mfi > 80:
                signals["MFI"] = "Overbought (>80) - high buying pressure"
            elif mfi < 20:
                signals["MFI"] = "Oversold (<20) - high selling pressure"
            else:
                signals["MFI"] = f"Neutral ({mfi:.1f})"

        # Williams %R
        if "Williams_R" in self.df.columns and not pd.isna(latest["Williams_R"]):
            williams = latest["Williams_R"]
            if williams > -20:
                signals["Williams_R"] = "Overbought (>-20) - potential reversal"
            elif williams < -80:
                signals["Williams_R"] = "Oversold (<-80) - potential reversal"
            else:
                signals["Williams_R"] = f"Neutral ({williams:.1f})"

        return signals

    def get_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive summary with latest values and signals

        Returns:
            Dictionary with complete technical analysis summary
        """
        return {
            "statistics": self.calculate_statistics(),
            "latest_values": self.get_latest_values(),
            "signals": self.generate_signals(),
            "state": self.crossovers(),
            "support_resistance": self.calculate_support_resistance(),
            "data_points": len(self.df),
            "date_range": {
                "start": format_date(self.df.index[0]) if not self.df.empty else None,
                "end": format_date(self.df.index[-1]) if not self.df.empty else None,
            },
        }

    def calculate_support_resistance(self, window: int = 20, num_levels: int = 3) -> Dict[str, Any]:
        """
        Calculate support and resistance levels from price data.

        Uses pivot point clustering to identify key levels where price
        has historically reversed.

        Args:
            window: Window size for detecting local extrema
            num_levels: Maximum number of levels per side

        Returns:
            Dictionary with support_levels, resistance_levels, and current_price
        """
        from ..scoring.trade_levels import calculate_support_resistance

        if self.df.empty or len(self.df) < window * 2:
            return {"support_levels": [], "resistance_levels": [], "current_price": None}

        support_levels, resistance_levels = calculate_support_resistance(
            self.df, window=window, num_levels=num_levels
        )

        current_price = float(self.df["Close"].iloc[-1])
        if pd.isna(current_price):
            valid = self.df["Close"].dropna()
            current_price = float(valid.iloc[-1]) if not valid.empty else None

        return {
            "support_levels": [round(s, 2) for s in support_levels],
            "resistance_levels": [round(r, 2) for r in resistance_levels],
            "current_price": round(current_price, 2) if current_price else None,
        }

    def format_markdown(self) -> List[str]:
        """
        Format technical analysis as detailed markdown report

        Returns:
            List of markdown lines for detailed technical analysis
        """
        md = []
        md.append("\n## Technical Analysis")
        md.append("")

        if self.df.empty:
            md.append("*No data available for technical analysis*")
            return md

        # Get currency symbol
        symbol = get_currency_symbol(self.currency)

        # Data range - format dates from index
        start_date = str(self.df.index[0])[:10]  # Get YYYY-MM-DD portion
        end_date = str(self.df.index[-1])[:10]
        md.append(f"**Analysis Period:** {start_date} to {end_date}")
        md.append(f"**Data Points:** {len(self.df)} trading days")
        md.append("")

        # Statistical Summary
        stats = self.calculate_statistics()
        if stats:
            md.append("### Statistical Summary")
            md.append("")
            md.append("| Metric | Value |")
            md.append("|--------|-------|")

            # Price statistics
            price = stats.get("price", {})
            if price:
                md.append(f"| Current Price | {symbol}{price.get('current', 0):.2f} |")
                md.append(
                    f"| Period High | {symbol}{price.get('high', 0):.2f} ({price.get('high_date', 'N/A')}) |"
                )
                md.append(
                    f"| Period Low | {symbol}{price.get('low', 0):.2f} ({price.get('low_date', 'N/A')}) |"
                )
                md.append(f"| Mean Price | {symbol}{price.get('mean', 0):.2f} |")
                md.append(
                    f"| Std Deviation | {symbol}{price.get('std_dev', 0):.2f} ({price.get('std_dev_pct', 0):.1f}%) |"
                )

            # Returns
            returns = stats.get("returns", {})
            if returns:
                md.append(f"| Period Return | {returns.get('period_return_pct', 0):+.2f}% |")
                md.append(f"| Daily Volatility | {returns.get('daily_volatility_pct', 0):.2f}% |")
                md.append(f"| Annual Volatility | {returns.get('annual_volatility_pct', 0):.1f}% |")

            # Volume
            vol = stats.get("volume", {})
            if vol:
                md.append(f"| Current Volume | {vol.get('current', 0):,.0f} |")
                md.append(f"| Average Volume | {vol.get('average', 0):,.0f} |")
                md.append(f"| Volume vs Avg | {vol.get('volume_vs_avg_pct', 0):+.1f}% |")
                md.append(
                    f"| Max Volume | {vol.get('max', 0):,.0f} ({vol.get('max_date', 'N/A')}) |"
                )

            md.append("")

        # Latest values
        latest_data = self.get_latest_values()
        md.append(f"### Current Price: {symbol}{latest_data['close_price']:.2f}")
        md.append(f"*As of {latest_data['date']}*")
        md.append("")

        # Trading Signals
        signals = self.generate_signals()
        if signals:
            md.append("### Trading Signals")
            md.append("")
            for indicator, signal in signals.items():
                md.append(f"**{indicator}:** {signal}")
            md.append("")

        # Indicator Categories
        indicators = latest_data["indicators"]

        # Trend Indicators
        md.append("### Trend Indicators")
        md.append("")
        md.append("| Indicator | Value |")
        md.append("|-----------|-------|")
        for key in ["SMA_20", "SMA_50", "SMA_200", "EMA_12", "EMA_26"]:
            if key in indicators and indicators[key] is not None:
                md.append(f"| {key} | {symbol}{indicators[key]:.2f} |")

        if "MACD" in indicators and indicators["MACD"] is not None:
            md.append(f"| MACD | {indicators['MACD']:.4f} |")
        if "MACD_signal" in indicators and indicators["MACD_signal"] is not None:
            md.append(f"| MACD Signal | {indicators['MACD_signal']:.4f} |")
        if "MACD_diff" in indicators and indicators["MACD_diff"] is not None:
            md.append(f"| MACD Histogram | {indicators['MACD_diff']:.4f} |")
        md.append("")

        # Momentum Indicators
        md.append("### Momentum Indicators")
        md.append("")
        md.append("| Indicator | Value | Interpretation |")
        md.append("|-----------|-------|----------------|")

        if "RSI" in indicators and indicators["RSI"] is not None:
            rsi = indicators["RSI"]
            interp = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
            md.append(f"| RSI (14) | {rsi:.2f} | {interp} |")

        if "MFI" in indicators and indicators["MFI"] is not None:
            mfi = indicators["MFI"]
            interp = "Overbought" if mfi > 80 else "Oversold" if mfi < 20 else "Neutral"
            md.append(f"| MFI (14) | {mfi:.2f} | {interp} |")

        if "Stoch_K" in indicators and indicators["Stoch_K"] is not None:
            stoch_k = indicators["Stoch_K"]
            interp = "Overbought" if stoch_k > 80 else "Oversold" if stoch_k < 20 else "Neutral"
            md.append(f"| Stochastic %K | {stoch_k:.2f} | {interp} |")
        if "Stoch_D" in indicators and indicators["Stoch_D"] is not None:
            stoch_d = indicators["Stoch_D"]
            interp = "Overbought" if stoch_d > 80 else "Oversold" if stoch_d < 20 else "Neutral"
            md.append(f"| Stochastic %D | {stoch_d:.2f} | {interp} |")

        if "Williams_R" in indicators and indicators["Williams_R"] is not None:
            williams = indicators["Williams_R"]
            interp = "Overbought" if williams > -20 else "Oversold" if williams < -80 else "Neutral"
            md.append(f"| Williams %R (14) | {williams:.2f} | {interp} |")
        md.append("")

        # Volatility & Trend Strength Indicators
        md.append("### Volatility & Trend Strength")
        md.append("")
        md.append("| Indicator | Value | Interpretation |")
        md.append("|-----------|-------|----------------|")

        # Bollinger Bands with price position
        bb_keys = ["BB_upper", "BB_middle", "BB_lower"]
        if all(key in indicators and indicators[key] is not None for key in bb_keys):
            close = latest_data["close_price"]
            bb_upper = indicators["BB_upper"]
            bb_middle = indicators["BB_middle"]
            bb_lower = indicators["BB_lower"]

            # Determine price position
            if close > bb_upper:
                bb_pos = "Above upper band"
            elif close < bb_lower:
                bb_pos = "Below lower band"
            elif close > bb_middle:
                bb_pos = "Upper half"
            else:
                bb_pos = "Lower half"

            md.append(f"| Bollinger Upper | {symbol}{bb_upper:.2f} | {bb_pos} |")
            md.append(f"| Bollinger Middle | {symbol}{bb_middle:.2f} | |")
            md.append(f"| Bollinger Lower | {symbol}{bb_lower:.2f} | |")
        else:
            # Fallback if not all BB values available
            for key in bb_keys:
                if key in indicators and indicators[key] is not None:
                    label = key.replace("BB_", "Bollinger ").replace("_", " ").title()
                    md.append(f"| {label} | {symbol}{indicators[key]:.2f} | |")

        if "ATR" in indicators and indicators["ATR"] is not None:
            current_atr = indicators["ATR"]
            # Compare to 20-day average to show if volatility is expanding/contracting
            if "ATR" in self.df.columns and len(self.df) >= 20:
                atr_sma = self.df["ATR"].rolling(20).mean().iloc[-1]
                if not pd.isna(atr_sma) and atr_sma > 0:
                    if current_atr > atr_sma * 1.2:
                        atr_interp = "Expanding (high)"
                    elif current_atr < atr_sma * 0.8:
                        atr_interp = "Contracting (low)"
                    else:
                        atr_interp = "Normal range"
                else:
                    atr_interp = "Volatility measure"
            else:
                atr_interp = "Volatility measure"
            md.append(f"| ATR (14) | {symbol}{current_atr:.2f} | {atr_interp} |")

        if "ADX" in indicators and indicators["ADX"] is not None:
            adx = indicators["ADX"]
            strength = "Strong" if adx > 25 else "Moderate" if adx > 20 else "Weak"
            md.append(f"| ADX (14) | {adx:.2f} | {strength} trend |")
        md.append("")

        # Volume Indicators
        md.append("### Volume Indicators")
        md.append("")
        md.append("| Indicator | Value |")
        md.append("|-----------|-------|")

        if "OBV" in indicators and indicators["OBV"] is not None:
            md.append(f"| OBV | {indicators['OBV']:,.0f} |")
        if "VWAP" in indicators and indicators["VWAP"] is not None:
            md.append(f"| VWAP | {symbol}{indicators['VWAP']:.2f} |")
        md.append("")

        # Recent Price Action (last 5 days)
        md.append("### Recent Price Action (Last 5 Days)")
        md.append("")
        # Add key indicators if available
        display_cols = ["Close", "Volume"]
        optional_cols = ["SMA_20", "RSI", "MACD"]
        for col in optional_cols:
            if col in self.df.columns:
                display_cols.append(col)

        # Format as markdown table
        md.append("| Date | " + " | ".join([col.replace("_", " ") for col in display_cols]) + " |")
        md.append("|" + "------|" * (len(display_cols) + 1))

        for idx, row in self.df[display_cols].tail(5).iterrows():
            date_str = str(idx)[:10]  # Get YYYY-MM-DD portion
            values = [date_str]
            for col in display_cols:
                val = row[col]
                if pd.isna(val):
                    values.append("N/A")
                elif col == "Volume":
                    values.append(f"{val:,.0f}")
                else:
                    values.append(f"{val:.2f}")
            md.append("| " + " | ".join(values) + " |")
        md.append("")

        return md


# ==================== Standalone Functions ====================


def calculate_relative_strength(
    price_data: pd.DataFrame,
    benchmark_data: Optional[pd.DataFrame] = None,
) -> Optional[Dict[str, Any]]:
    """
    Calculate IBD-style Relative Strength Rating (1-99).

    Weighted price performance vs. benchmark over multiple timeframes:
    - 40% weight on 3-month performance
    - 20% weight on 6-month performance
    - 20% weight on 9-month performance
    - 20% weight on 12-month performance

    An RS rating of 80 means the stock outperformed 80% of the benchmark
    over these combined timeframes.

    Args:
        price_data: DataFrame with 'Close' prices (needs 252+ days ideally)
        benchmark_data: Optional benchmark DataFrame. If None, returns raw RS score.

    Returns:
        Dictionary with RS rating components, or None if insufficient data
    """
    if price_data is None or price_data.empty or "Close" not in price_data.columns:
        return None

    prices = _closes_by_date(price_data["Close"])
    if len(prices) < 63:  # Need at least 3 months
        return None

    benchmark = None
    if benchmark_data is not None and not benchmark_data.empty and "Close" in benchmark_data:
        benchmark = _closes_by_date(benchmark_data["Close"])
    end = prices.index[-1]
    current_price = float(prices.iloc[-1])

    # Calculate returns over each timeframe
    components = {}
    weights = {"3mo": 0.40, "6mo": 0.20, "9mo": 0.20, "12mo": 0.20}
    periods = {"3mo": 63, "6mo": 126, "9mo": 189, "12mo": 252}

    stock_weighted_return = 0.0
    benchmark_weighted_return = 0.0
    total_weight = 0.0

    # Each horizon starts on the stock's own trading date `days` bars back. The
    # benchmark is read on the same dates (its last close on or before them),
    # and a horizon counts only when both series cover it, so a short or
    # missing benchmark history isn't read as a 0% return.
    for label, days in periods.items():
        if len(prices) < days:
            continue
        start = prices.index[-days]
        past_price = float(prices.iloc[-days])
        if past_price <= 0:
            continue
        bm_return = 0.0
        if benchmark is not None:
            bm_past, bm_now = _close_on(benchmark, start), _close_on(benchmark, end)
            if bm_past is None or bm_now is None or bm_past <= 0:
                continue
            bm_return = (bm_now - bm_past) / bm_past
        stock_return = (current_price - past_price) / past_price
        components[f"return_{label}"] = stock_return * 100
        weight = weights[label]
        stock_weighted_return += stock_return * weight
        benchmark_weighted_return += bm_return * weight
        total_weight += weight

    if total_weight == 0:
        return None

    # Normalize weighted return
    stock_weighted_return /= total_weight
    benchmark_weighted_return /= total_weight

    # Relative strength vs benchmark
    relative_return = stock_weighted_return - benchmark_weighted_return

    # Convert to a 1-99 scale (roughly)
    # A relative return of 0% = 50, +100% = ~99, -100% = ~1
    # Using sigmoid-like mapping

    rs_raw = 50 + 50 * math.tanh(relative_return * 2)
    rs_rating = max(1, min(99, int(rs_raw)))

    return {
        "rs_rating": rs_rating,
        "weighted_return_pct": stock_weighted_return * 100,
        "benchmark_weighted_return_pct": benchmark_weighted_return * 100,
        "relative_return_pct": relative_return * 100,
        "components": components,
        "interpretation": (
            "Very strong momentum (top 20%)"
            if rs_rating >= 80
            else "Strong momentum"
            if rs_rating >= 60
            else "Average momentum"
            if rs_rating >= 40
            else "Weak momentum"
            if rs_rating >= 20
            else "Very weak momentum (bottom 20%)"
        ),
    }


def _closes_by_date(close: pd.Series) -> pd.Series:
    """Positive closes indexed by tz-naive trading date, one per day, in order."""
    out = pd.to_numeric(close, errors="coerce").dropna()
    out = out[out > 0]
    out.index = trading_dates(pd.DatetimeIndex(out.index))
    return out[~out.index.duplicated(keep="last")].sort_index()


def _close_on(closes: pd.Series, date: pd.Timestamp) -> Optional[float]:
    """The last close on or before `date`, or None if the series starts after it."""
    if closes.empty or closes.index[0] > date:
        return None
    return float(closes[:date].iloc[-1])


def _finite(value: Any) -> float:
    """A float, or NaN for a missing or non-numeric value."""
    try:
        return float(value)
    except TypeError, ValueError:
        return math.nan
