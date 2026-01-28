"""
Example: Data Inspection
Inspect and validate fetched data
"""

from src.data_fetcher import DataFetcher
import pandas as pd

def inspect_data(ticker: str, period: str = "1y"):
    """Inspect data quality and characteristics"""
    fetcher = DataFetcher()
    data = fetcher.fetch_ticker(ticker, period=period)
    
    print(f"{'=' * 60}")
    print(f"Data Inspection: {ticker}")
    print(f"{'=' * 60}\n")
    
    # Basic info
    print("1. Basic Information")
    print("-" * 40)
    print(f"Shape: {data.shape[0]} rows × {data.shape[1]} columns")
    print(f"Columns: {list(data.columns)}")
    print(f"Date range: {data.index[0].date()} to {data.index[-1].date()}")
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
    print(f"Highest Close: ${data['Close'].max():.2f} on {data['Close'].idxmax().date()}")
    print(f"Lowest Close:  ${data['Close'].min():.2f} on {data['Close'].idxmin().date()}")
    print(f"Current Close: ${data['Close'].iloc[-1]:.2f}")
    print(f"Average Close: ${data['Close'].mean():.2f}")
    
    # Volume analysis
    print("\n6. Volume Analysis")
    print("-" * 40)
    print(f"Average Volume: {data['Volume'].mean():,.0f}")
    print(f"Max Volume:     {data['Volume'].max():,.0f} on {data['Volume'].idxmax().date()}")
    print(f"Min Volume:     {data['Volume'].min():,.0f} on {data['Volume'].idxmin().date()}")
    
    return data


def main():
    # Inspect AAPL
    aapl = inspect_data("AAPL", period="1y")
    
    # Quick comparison of multiple stocks
    print("\n" + "=" * 60)
    print("Quick Comparison: FAANG Stocks")
    print("=" * 60 + "\n")
    
    tickers = ["META", "AAPL", "AMZN", "NFLX", "GOOGL"]
    fetcher = DataFetcher()
    
    comparison = []
    for ticker in tickers:
        try:
            data = fetcher.fetch_ticker(ticker, period="1y")
            start_price = data['Close'].iloc[0]
            end_price = data['Close'].iloc[-1]
            return_pct = ((end_price / start_price) - 1) * 100
            volatility = data['Close'].pct_change().std() * 100
            
            comparison.append({
                'Ticker': ticker,
                'Start': f"${start_price:.2f}",
                'End': f"${end_price:.2f}",
                'Return %': f"{return_pct:.2f}%",
                'Daily Vol %': f"{volatility:.2f}%",
                'Avg Volume': f"{data['Volume'].mean():,.0f}"
            })
        except Exception as e:
            print(f"Error with {ticker}: {e}")
    
    df = pd.DataFrame(comparison)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
