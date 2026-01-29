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
        
        # Volatility indicators
        self.calculate_bollinger_bands()
        self.calculate_atr()
        
        # Volume indicators
        self.calculate_obv()
        self.calculate_vwap()
        
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
