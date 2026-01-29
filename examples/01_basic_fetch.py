"""
Example: Basic Data Fetching
Demonstrates how to fetch stock data using the DataFetcher
"""

from src.data_fetcher import DataFetcher


def main():
    # Initialize fetcher
    fetcher = DataFetcher(cache_dir="data")

    # Example 1: Fetch single ticker
    print("=" * 60)
    print("Example 1: Fetch Exelixis (EXE.TO) - Last 1 month")
    print("=" * 60)

    aapl_data = fetcher.fetch_ticker("EXE.TO", period="1mo")
    print(f"\nData shape: {aapl_data.shape}")
    print(f"Date range: {aapl_data.index[0]} to {aapl_data.index[-1]}")
    print("\nFirst 5 rows:")
    print(aapl_data.head())
    print("\nLast 5 rows:")
    print(aapl_data.tail())

    # Example 2: Get ticker info
    print("\n" + "=" * 60)
    print("Example 2: Get Ticker Information")
    print("=" * 60)

    info = fetcher.get_ticker_info("AAPL")
    for key, value in info.items():
        print(f"{key:15}: {value}")

    # Example 3: Fetch multiple tickers
    print("\n" + "=" * 60)
    print("Example 3: Fetch Multiple Tickers")
    print("=" * 60)

    tickers = ["AAPL", "MSFT", "GOOGL", "TSLA"]
    multi_data = fetcher.fetch_multiple_tickers(tickers, period="6mo")

    print(f"\nFetched {len(multi_data)} tickers:")
    for ticker, data in multi_data.items():
        print(f"{ticker:6} - {len(data)} rows, Latest close: ${data['Close'].iloc[-1]:.2f}")

    # Example 4: Custom date range
    print("\n" + "=" * 60)
    print("Example 4: Custom Date Range")
    print("=" * 60)

    custom_data = fetcher.fetch_ticker("MSFT", start="2024-01-01", end="2024-12-31", interval="1d")
    print(f"\nMSFT data from 2024:")
    print(f"Rows: {len(custom_data)}")
    print(
        f"Price change: ${custom_data['Close'].iloc[0]:.2f} -> ${custom_data['Close'].iloc[-1]:.2f}"
    )
    print(
        f"Return: {((custom_data['Close'].iloc[-1] / custom_data['Close'].iloc[0]) - 1) * 100:.2f}%"
    )


if __name__ == "__main__":
    main()
