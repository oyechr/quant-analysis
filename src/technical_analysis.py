"""
Technical Analysis Module
Calculates technical indicators from price data using ta library
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
import logging

# Import ta submodules
from ta import trend, momentum, volatility, volume

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """
    Calculates technical indicators from OHLCV price data
    
    Uses ta library for standard technical analysis indicators.
    Separates concerns: price data storage vs. indicator calculation.
    """
    
    def __init__(self, price_data: pd.DataFrame):
        """
        Initialize analyzer with price data
        
        Args:
            price_data: DataFrame with OHLCV columns (Open, High, Low, Close, Volume)
                       Must have datetime index
        """

        # Validate required columns
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing = [col for col in required_cols if col not in price_data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        self.df = price_data.copy()
        
    # ==================== Trend Indicators ====================
    
    def calculate_moving_averages(
        self,
        sma_periods: List[int] = [20, 50, 200],
        ema_periods: List[int] = [12, 26]
    ) -> pd.DataFrame:
        """
        Calculate Simple and Exponential Moving Averages
        
        Args:
            sma_periods: Periods for SMA calculation
            ema_periods: Periods for EMA calculation
            
        Returns:
            DataFrame with SMA and EMA columns added
        """
        for period in sma_periods:
            col_name = f'SMA_{period}'
            self.df[col_name] = trend.sma_indicator(self.df['Close'], window=period)
            
        for period in ema_periods:
            col_name = f'EMA_{period}'
            self.df[col_name] = trend.ema_indicator(self.df['Close'], window=period)
        
        return self.df
    
    def calculate_macd(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> pd.DataFrame:
        """
        Calculate MACD (Moving Average Convergence Divergence)
        
        Args:
            fast: Fast EMA period
            slow: Slow EMA period
            signal: Signal line period
            
        Returns:
            DataFrame with MACD, MACD_signal, MACD_diff columns
        """
        self.df['MACD'] = trend.macd(self.df['Close'], window_slow=slow, window_fast=fast, fillna=False)
        self.df['MACD_signal'] = trend.macd_signal(self.df['Close'], window_slow=slow, window_fast=fast, window_sign=signal, fillna=False)
        self.df['MACD_diff'] = trend.macd_diff(self.df['Close'], window_slow=slow, window_fast=fast, window_sign=signal, fillna=False)
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
        self.df[f'RSI_{period}'] = momentum.rsi(self.df['Close'], window=period)
        return self.df
    
    def calculate_stochastic(
        self,
        k_period: int = 14,
        d_period: int = 3
    ) -> pd.DataFrame:
        """
        Calculate Stochastic Oscillator
        
        Args:
            k_period: %K period
            d_period: %D period (signal line)
            
        Returns:
            DataFrame with Stochastic %K and %D columns
        """
        self.df['Stoch_K'] = momentum.stoch(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            window=k_period,
            smooth_window=d_period
        )
        self.df['Stoch_D'] = momentum.stoch_signal(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            window=k_period,
            smooth_window=d_period
        )
        return self.df
    
    # ==================== Volatility Indicators ====================
    
    def calculate_bollinger_bands(
        self,
        period: int = 20,
        std_dev: float = 2.0
    ) -> pd.DataFrame:
        """
        Calculate Bollinger Bands
        
        Args:
            period: Moving average period
            std_dev: Number of standard deviations
            
        Returns:
            DataFrame with BB_lower, BB_middle, BB_upper columns
        """
        bb = volatility.BollingerBands(
            close=self.df['Close'],
            window=period,
            window_dev=int(std_dev)
        )
        self.df['BB_upper'] = bb.bollinger_hband()
        self.df['BB_middle'] = bb.bollinger_mavg()
        self.df['BB_lower'] = bb.bollinger_lband()
        return self.df
    
    def calculate_atr(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate ATR (Average True Range)
        
        Args:
            period: Lookback period
            
        Returns:
            DataFrame with ATR column added
        """
        self.df[f'ATR_{period}'] = volatility.average_true_range(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            window=period
        )
        return self.df
    
    def calculate_adx(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate ADX (Average Directional Index) - Trend Strength
        
        Args:
            period: Lookback period
            
        Returns:
            DataFrame with ADX column added
        """
        self.df[f'ADX_{period}'] = trend.adx(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            window=period
        )
        return self.df
    
    # ==================== Volume Indicators ====================
    
    def calculate_obv(self) -> pd.DataFrame:
        """
        Calculate OBV (On-Balance Volume)
        
        Returns:
            DataFrame with OBV column added
        """
        self.df['OBV'] = volume.on_balance_volume(self.df['Close'], self.df['Volume'])
        return self.df
    
    def calculate_vwap(self) -> pd.DataFrame:
        """
        Calculate VWAP (Volume Weighted Average Price)
        
        Returns:
            DataFrame with VWAP column added
        """
        self.df['VWAP'] = volume.volume_weighted_average_price(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            self.df['Volume']
        )
        return self.df
    
    def calculate_mfi(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate MFI (Money Flow Index) - Volume-weighted RSI
        
        Args:
            period: Lookback period
            
        Returns:
            DataFrame with MFI column added
        """
        self.df[f'MFI_{period}'] = volume.money_flow_index(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            self.df['Volume'],
            window=period
        )
        return self.df
    
    def calculate_williams_r(self, period: int = 14) -> pd.DataFrame:
        """
        Calculate Williams %R - Momentum Oscillator
        
        Args:
            period: Lookback period
            
        Returns:
            DataFrame with Williams %R column added
        """
        self.df[f'Williams_R_{period}'] = momentum.williams_r(
            self.df['High'],
            self.df['Low'],
            self.df['Close'],
            lbp=period
        )
        return self.df
    
    # ==================== All-in-One Methods ====================
    
    def calculate_all_indicators(self) -> pd.DataFrame:
        """
        Calculate all standard technical indicators
        
        Returns:
            DataFrame with all indicators added
        """
        logger.info("Calculating all technical indicators...")
        
        # Trend indicators
        self.calculate_moving_averages()
        self.calculate_macd()
        
        # Momentum indicators
        self.calculate_rsi()
        self.calculate_stochastic()
        self.calculate_williams_r()
        
        # Volatility indicators
        self.calculate_bollinger_bands()
        self.calculate_atr()
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
        base_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']
        indicator_cols = [col for col in self.df.columns if col not in base_cols]
        
        result = {
            'date': str(latest.name),
            'close_price': float(latest['Close']),
            'indicators': {}
        }
        
        for col in indicator_cols:
            value = latest[col]
            # Handle NaN values
            result['indicators'][col] = None if pd.isna(value) else float(value)
        
        return result
    
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
        if 'RSI_14' in self.df.columns and not pd.isna(latest['RSI_14']):
            rsi = latest['RSI_14']
            if rsi > 70:
                signals['RSI'] = 'Overbought (>70) - potential sell signal'
            elif rsi < 30:
                signals['RSI'] = 'Oversold (<30) - potential buy signal'
            else:
                signals['RSI'] = f'Neutral ({rsi:.1f})'
        
        # MACD signals
        if 'MACD' in self.df.columns and 'MACD_signal' in self.df.columns:
            macd = latest['MACD']
            macd_signal = latest['MACD_signal']
            prev_macd = prev['MACD']
            prev_signal = prev['MACD_signal']
            
            if not pd.isna(macd) and not pd.isna(macd_signal):
                # Bullish crossover
                if prev_macd < prev_signal and macd > macd_signal:
                    signals['MACD'] = 'Bullish crossover - buy signal'
                # Bearish crossover
                elif prev_macd > prev_signal and macd < macd_signal:
                    signals['MACD'] = 'Bearish crossover - sell signal'
                elif macd > macd_signal:
                    signals['MACD'] = 'Bullish'
                else:
                    signals['MACD'] = 'Bearish'
        
        # Moving average trend
        if 'SMA_50' in self.df.columns and 'SMA_200' in self.df.columns:
            sma50 = latest['SMA_50']
            sma200 = latest['SMA_200']
            close = latest['Close']
            
            if not pd.isna(sma50) and not pd.isna(sma200):
                if sma50 > sma200:
                    signals['MA_Trend'] = 'Bullish (Golden Cross)'
                else:
                    signals['MA_Trend'] = 'Bearish (Death Cross)'
                
                # Price vs MA
                if close > sma50 > sma200:
                    signals['Price_Position'] = 'Strong uptrend (above both MAs)'
                elif close < sma50 < sma200:
                    signals['Price_Position'] = 'Strong downtrend (below both MAs)'
        
        # Bollinger Bands
        if all(col in self.df.columns for col in ['BB_lower', 'BB_middle', 'BB_upper']):
            bb_lower = latest['BB_lower']
            bb_upper = latest['BB_upper']
            close = latest['Close']
            
            if not pd.isna(bb_lower) and not pd.isna(bb_upper):
                if close > bb_upper:
                    signals['Bollinger_Bands'] = 'Price above upper band - overbought'
                elif close < bb_lower:
                    signals['Bollinger_Bands'] = 'Price below lower band - oversold'
                else:
                    signals['Bollinger_Bands'] = 'Price within bands - normal'
        
        # ADX - Trend Strength
        if 'ADX_14' in self.df.columns and not pd.isna(latest['ADX_14']):
            adx = latest['ADX_14']
            if adx > 25:
                signals['ADX'] = f'Strong trend ({adx:.1f})'
            elif adx > 20:
                signals['ADX'] = f'Moderate trend ({adx:.1f})'
            else:
                signals['ADX'] = f'Weak/no trend ({adx:.1f})'
        
        # MFI - Money Flow
        if 'MFI_14' in self.df.columns and not pd.isna(latest['MFI_14']):
            mfi = latest['MFI_14']
            if mfi > 80:
                signals['MFI'] = 'Overbought (>80) - high buying pressure'
            elif mfi < 20:
                signals['MFI'] = 'Oversold (<20) - high selling pressure'
            else:
                signals['MFI'] = f'Neutral ({mfi:.1f})'
        
        # Williams %R
        if 'Williams_R_14' in self.df.columns and not pd.isna(latest['Williams_R_14']):
            williams = latest['Williams_R_14']
            if williams > -20:
                signals['Williams_R'] = 'Overbought (>-20) - potential reversal'
            elif williams < -80:
                signals['Williams_R'] = 'Oversold (<-80) - potential reversal'
            else:
                signals['Williams_R'] = f'Neutral ({williams:.1f})'
        
        return signals
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive summary with latest values and signals
        
        Returns:
            Dictionary with complete technical analysis summary
        """
        return {
            'latest_values': self.get_latest_values(),
            'signals': self.generate_signals(),
            'data_points': len(self.df),
            'date_range': {
                'start': str(self.df.index[0]) if not self.df.empty else None,
                'end': str(self.df.index[-1]) if not self.df.empty else None
            }
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
        
        # Data range - format dates from index
        start_date = str(self.df.index[0])[:10]  # Get YYYY-MM-DD portion
        end_date = str(self.df.index[-1])[:10]
        md.append(f"**Analysis Period:** {start_date} to {end_date}")
        md.append(f"**Data Points:** {len(self.df)} trading days")
        md.append("")
        
        # Latest values
        latest_data = self.get_latest_values()
        md.append(f"### Current Price: ${latest_data['close_price']:.2f}")
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
        indicators = latest_data['indicators']
        
        # Trend Indicators
        md.append("### Trend Indicators")
        md.append("")
        md.append("| Indicator | Value |")
        md.append("|-----------|-------|")
        for key in ['SMA_20', 'SMA_50', 'SMA_200', 'EMA_12', 'EMA_26']:
            if key in indicators and indicators[key] is not None:
                md.append(f"| {key} | ${indicators[key]:.2f} |")
        
        if 'MACD' in indicators and indicators['MACD'] is not None:
            md.append(f"| MACD | {indicators['MACD']:.4f} |")
        if 'MACD_signal' in indicators and indicators['MACD_signal'] is not None:
            md.append(f"| MACD Signal | {indicators['MACD_signal']:.4f} |")
        if 'MACD_diff' in indicators and indicators['MACD_diff'] is not None:
            md.append(f"| MACD Histogram | {indicators['MACD_diff']:.4f} |")
        md.append("")
        
        # Momentum Indicators
        md.append("### Momentum Indicators")
        md.append("")
        md.append("| Indicator | Value | Interpretation |")
        md.append("|-----------|-------|----------------|")
        
        if 'RSI_14' in indicators and indicators['RSI_14'] is not None:
            rsi = indicators['RSI_14']
            interp = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
            md.append(f"| RSI (14) | {rsi:.2f} | {interp} |")
        
        if 'MFI_14' in indicators and indicators['MFI_14'] is not None:
            mfi = indicators['MFI_14']
            interp = "Overbought" if mfi > 80 else "Oversold" if mfi < 20 else "Neutral"
            md.append(f"| MFI (14) | {mfi:.2f} | {interp} |")
        
        if 'Stoch_K' in indicators and indicators['Stoch_K'] is not None:
            stoch_k = indicators['Stoch_K']
            interp = "Overbought" if stoch_k > 80 else "Oversold" if stoch_k < 20 else "Neutral"
            md.append(f"| Stochastic %K | {stoch_k:.2f} | {interp} |")
        if 'Stoch_D' in indicators and indicators['Stoch_D'] is not None:
            stoch_d = indicators['Stoch_D']
            interp = "Overbought" if stoch_d > 80 else "Oversold" if stoch_d < 20 else "Neutral"
            md.append(f"| Stochastic %D | {stoch_d:.2f} | {interp} |")
        
        if 'Williams_R_14' in indicators and indicators['Williams_R_14'] is not None:
            williams = indicators['Williams_R_14']
            interp = "Overbought" if williams > -20 else "Oversold" if williams < -80 else "Neutral"
            md.append(f"| Williams %R (14) | {williams:.2f} | {interp} |")
        md.append("")
        
        # Volatility & Trend Strength Indicators
        md.append("### Volatility & Trend Strength")
        md.append("")
        md.append("| Indicator | Value | Interpretation |")
        md.append("|-----------|-------|----------------|")
        
        # Bollinger Bands with price position
        bb_keys = ['BB_upper', 'BB_middle', 'BB_lower']
        if all(key in indicators and indicators[key] is not None for key in bb_keys):
            close = latest_data['close_price']
            bb_upper = indicators['BB_upper']
            bb_middle = indicators['BB_middle']
            bb_lower = indicators['BB_lower']
            
            # Determine price position
            if close > bb_upper:
                bb_pos = "Above upper band"
            elif close < bb_lower:
                bb_pos = "Below lower band"
            elif close > bb_middle:
                bb_pos = "Upper half"
            else:
                bb_pos = "Lower half"
            
            md.append(f"| Bollinger Upper | ${bb_upper:.2f} | {bb_pos} |")
            md.append(f"| Bollinger Middle | ${bb_middle:.2f} | |")
            md.append(f"| Bollinger Lower | ${bb_lower:.2f} | |")
        else:
            # Fallback if not all BB values available
            for key in bb_keys:
                if key in indicators and indicators[key] is not None:
                    label = key.replace('BB_', 'Bollinger ').replace('_', ' ').title()
                    md.append(f"| {label} | ${indicators[key]:.2f} | |")
        
        if 'ATR_14' in indicators and indicators['ATR_14'] is not None:
            current_atr = indicators['ATR_14']
            # Compare to 20-day average to show if volatility is expanding/contracting
            if 'ATR_14' in self.df.columns and len(self.df) >= 20:
                atr_sma = self.df['ATR_14'].rolling(20).mean().iloc[-1]
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
            md.append(f"| ATR (14) | ${current_atr:.2f} | {atr_interp} |")
        
        if 'ADX_14' in indicators and indicators['ADX_14'] is not None:
            adx = indicators['ADX_14']
            strength = "Strong" if adx > 25 else "Moderate" if adx > 20 else "Weak"
            md.append(f"| ADX (14) | {adx:.2f} | {strength} trend |")
        md.append("")
        
        # Volume Indicators
        md.append("### Volume Indicators")
        md.append("")
        md.append("| Indicator | Value |")
        md.append("|-----------|-------|")
        
        if 'OBV' in indicators and indicators['OBV'] is not None:
            md.append(f"| OBV | {indicators['OBV']:,.0f} |")
        if 'VWAP' in indicators and indicators['VWAP'] is not None:
            md.append(f"| VWAP | ${indicators['VWAP']:.2f} |")
        md.append("")
        
        # Recent Price Action (last 5 days)
        md.append("### Recent Price Action (Last 5 Days)")
        md.append("")
        recent = self.df[['Close', 'Volume']].tail(5)
        
        # Add key indicators if available
        display_cols = ['Close', 'Volume']
        optional_cols = ['SMA_20', 'RSI_14', 'MACD']
        for col in optional_cols:
            if col in self.df.columns:
                display_cols.append(col)
        
        # Format as markdown table
        md.append("| Date | " + " | ".join([col.replace('_', ' ') for col in display_cols]) + " |")
        md.append("|" + "------|" * (len(display_cols) + 1))
        
        for idx, row in self.df[display_cols].tail(5).iterrows():
            date_str = str(idx)[:10]  # Get YYYY-MM-DD portion
            values = [date_str]
            for col in display_cols:
                val = row[col]
                if pd.isna(val):
                    values.append('N/A')
                elif col == 'Volume':
                    values.append(f"{val:,.0f}")
                else:
                    values.append(f"{val:.2f}")
            md.append("| " + " | ".join(values) + " |")
        md.append("")
        
        return md


def analyze_ticker(price_data: pd.DataFrame) -> Dict[str, Any]:
    """
    Convenience function to analyze price data with all indicators
    
    Args:
        price_data: DataFrame with OHLCV data
        
    Returns:
        Dictionary with complete technical analysis
    """
    analyzer = TechnicalAnalyzer(price_data)
    analyzer.calculate_all_indicators()
    return analyzer.get_summary()
