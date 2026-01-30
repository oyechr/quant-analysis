"""
Example: Data Inspection
Inspect and validate fetched data
"""

from pathlib import Path

import pandas as pd

from src.data_fetcher import DataFetcher
from src.utils import format_date


def inspect_data(ticker: str, period: str = "1y", use_cache: bool = True):
    """Inspect data quality and characteristics"""
    fetcher = DataFetcher()

    # Show cache location
    cache_file = fetcher._get_cache_filename(ticker.upper(), None, None, period, "1d")
    cache_exists = cache_file.exists()

    print(f"{'=' * 60}")
    print(f"Cache Status")
    print(f"{'=' * 60}")
    print(f"Cache location: {cache_file}")
    print(f"Cache exists: {'Yes ✓' if cache_exists else 'No (will fetch from Yahoo Finance)'}")
    print(f"Use cache: {use_cache}\n")

    data = fetcher.fetch_ticker(ticker, period=period, use_cache=use_cache)

    print(f"{'=' * 60}")
    print(f"Data Inspection: {ticker}")
    print(f"{'=' * 60}\n")

    # Basic info
    print("1. Basic Information")
    print("-" * 40)
    print(f"Shape: {data.shape[0]} rows × {data.shape[1]} columns")
    print(f"Columns: {list(data.columns)}")
    print(
        f"Date range: {format_date(data.index[0], 'readable')} to {format_date(data.index[-1], 'readable')}"
    )
    print(f"Trading days: {len(data)}")

    # Data types
    print("\n2. Data Types")
    print("-" * 40)
    print(data.dtypes)

    # Missing values
    print("\n3. Missing Values")
    print("-" * 40)
    missing = data.isnull().sum()
    if missing.sum() == 0:
        print("No missing values ✓")
    else:
        print(missing[missing > 0])

    # Statistical summary
    print("\n4. Statistical Summary")
    print("-" * 40)
    print(data.describe())

    # Price ranges
    print("\n5. Price Information")
    print("-" * 40)
    print(
        f"Highest Close: ${data['Close'].max():.2f} on {format_date(data['Close'].idxmax(), 'readable')}"
    )
    print(
        f"Lowest Close:  ${data['Close'].min():.2f} on {format_date(data['Close'].idxmin(), 'readable')}"
    )
    print(f"Current Close: ${data['Close'].iloc[-1]:.2f}")
    print(f"Average Close: ${data['Close'].mean():.2f}")

    # Volume analysis
    print("\n6. Volume Analysis")
    print("-" * 40)
    print(f"Average Volume: {data['Volume'].mean():,.0f}")
    print(
        f"Max Volume:     {data['Volume'].max():,.0f} on {format_date(data['Volume'].idxmax(), 'readable')}"
    )
    print(
        f"Min Volume:     {data['Volume'].min():,.0f} on {format_date(data['Volume'].idxmin(), 'readable')}"
    )

    # Return calculation
    print("\n7. Performance")
    print("-" * 40)
    start_price = data["Close"].iloc[0]
    end_price = data["Close"].iloc[-1]
    return_pct = ((end_price / start_price) - 1) * 100
    volatility = data["Close"].pct_change().std() * 100
    print(f"Period Return: {return_pct:+.2f}%")
    print(f"Daily Volatility: {volatility:.2f}%")

    return data


def main():
    # Inspect single ticker with cache demonstration
    print("=" * 60)
    print("Data Inspection Example")
    print("=" * 60 + "\n")

    ticker = "EXE.TO"
    period = "1y"

    # First run - may use cache if available
    print("Test 1: Using cache (if available)")
    print("-" * 60)
    data = inspect_data(ticker, period=period, use_cache=True)

    # Optional: Force fresh fetch
    print("\n\n" + "=" * 60)
    print("Test 2: Force fresh fetch (use_cache=False)")
    print("=" * 60 + "\n")
    user_input = input("Fetch fresh data? (y/n): ").strip().lower()
    if user_input == "y":
        data_fresh = inspect_data(ticker, period=period, use_cache=False)
        print("\n✓ Fresh data fetched and cached")
    else:
        print("\nSkipped fresh fetch")


if __name__ == "__main__":
    main()
