"""
Example: Technical Analysis
Demonstrates calculating technical indicators from price data
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import DataFetcher
from src.technical_analysis import TechnicalAnalyzer
import json


def main():
    print("=" * 70)
    print("Technical Analysis Example")
    print("=" * 70)
    
    # Initialize fetcher
    fetcher = DataFetcher(cache_dir="data")
    ticker = "EXE.TO"
    
    # Fetch 1 year of data (needed for 200-day SMA)
    print(f"\nFetching 1 year of price data for {ticker}...")
    price_data = fetcher.fetch_ticker(ticker, period="1y")
    print(f"  ✓ Fetched {len(price_data)} trading days")
    
    # Initialize technical analyzer
    print(f"\nInitializing Technical Analyzer...")
    analyzer = TechnicalAnalyzer(price_data)
    
    # Calculate all indicators
    print("\nCalculating technical indicators...")
    df_with_indicators = analyzer.calculate_all_indicators()
    
    print(f"  ✓ Original columns: {list(price_data.columns)}")
    print(f"  ✓ Total columns now: {len(df_with_indicators.columns)}")
    print(f"  ✓ Indicators added: {len(df_with_indicators.columns) - len(price_data.columns)}")
    
    # Show indicator columns
    base_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']
    indicator_cols = [col for col in df_with_indicators.columns if col not in base_cols]
    print(f"\n  Calculated indicators:")
    for col in sorted(indicator_cols):
        print(f"    - {col}")
    
    # Get latest values
    print("\n" + "=" * 70)
    print("Latest Indicator Values")
    print("=" * 70)
    
    latest = analyzer.get_latest_values()
    print(f"\nDate: {latest['date']}")
    print(f"Close Price: ${latest['close_price']:.2f}")
    print("\nIndicators:")
    for name, value in sorted(latest['indicators'].items()):
        if value is not None:
            print(f"  {name:20s}: {value:>10.2f}")
        else:
            print(f"  {name:20s}: {'N/A':>10s}")
    
    # Get trading signals
    print("\n" + "=" * 70)
    print("Trading Signals")
    print("=" * 70)
    
    signals = analyzer.generate_signals()
    if signals:
        for indicator, signal in signals.items():
            print(f"\n{indicator}:")
            print(f"  {signal}")
    else:
        print("\nNot enough data to generate signals")
    
    # Get full summary
    print("\n" + "=" * 70)
    print("Complete Summary")
    print("=" * 70)
    
    summary = analyzer.get_summary()
    print(f"\nData Range: {summary['date_range']['start']} to {summary['date_range']['end']}")
    print(f"Data Points: {summary['data_points']}")
    print(f"Signals Generated: {len(summary['signals'])}")
    
    # Save summary to JSON for inspection
    output_file = Path("data") / ticker / "technical_analysis.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n✓ Technical analysis saved to: {output_file}")
    
    # Show sample of data with indicators
    print("\n" + "=" * 70)
    print("Sample Data (Last 5 Days)")
    print("=" * 70)
    print("\nPrice + Key Indicators:")
    display_cols = ['Close', 'SMA_20', 'SMA_50', 'RSI_14', 'MACD_12_26_9']
    available_cols = [col for col in display_cols if col in df_with_indicators.columns]
    print(df_with_indicators[available_cols].tail())
    
    print("\n" + "=" * 70)
    print("Technical Analysis Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
