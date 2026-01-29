"""
Example: Testing Fundamental Data Features
Demonstrates new methods for fetching fundamentals, earnings, and institutional data
"""

import sys
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import json

from src.data_fetcher import DataFetcher


def main():
    # Initialize fetcher
    fetcher = DataFetcher(cache_dir="data")
    ticker = "EXE.TO"  # Change this to test different stocks

    print("=" * 70)
    print(f"Testing Fundamental Data Features for {ticker}")
    print("=" * 70)

    # Test 1: Enhanced ticker info
    print("\n" + "=" * 70)
    print("Test 1: Enhanced Ticker Info (Valuation & Financial Metrics)")
    print("=" * 70)

    info = fetcher.get_ticker_info(ticker)

    print(f"\nBasic Info:")
    print(f"  Symbol: {info['symbol']}")
    print(f"  Name: {info['name']}")
    print(f"  Sector: {info['sector']}")
    print(f"  Industry: {info['industry']}")

    print(f"\nValuation Metrics:")
    print(f"  P/E Ratio: {info['pe_ratio']}")
    print(f"  Forward P/E: {info['forward_pe']}")
    print(f"  PEG Ratio: {info['peg_ratio']}")
    print(f"  Price/Book: {info['price_to_book']}")
    print(f"  Price/Sales: {info['price_to_sales']}")

    print(f"\nProfitability:")
    print(f"  Profit Margin: {info['profit_margin']}")
    print(f"  Operating Margin: {info['operating_margin']}")
    print(f"  ROE: {info['roe']}")
    print(f"  ROA: {info['roa']}")

    print(f"\nFinancial Health:")
    print(f"  Debt/Equity: {info['debt_to_equity']}")
    print(f"  Current Ratio: {info['current_ratio']}")
    print(f"  Quick Ratio: {info['quick_ratio']}")

    print(f"\nDividends & Risk:")
    print(f"  Dividend Yield: {info['dividend_yield']}")
    print(f"  Payout Ratio: {info['payout_ratio']}")
    print(f"  Beta: {info['beta']}")

    # Test 2: Fundamentals
    print("\n" + "=" * 70)
    print("Test 2: Fundamental Financial Statements")
    print("=" * 70)

    fundamentals = fetcher.fetch_fundamentals(ticker)

    print("\nAvailable statements:")
    for key in fundamentals.keys():
        df = fundamentals[key]
        print(f"  {key}: {df.shape if not df.empty else 'Empty'}")

    # Show sample from quarterly income statement
    if not fundamentals["income_stmt_quarterly"].empty:
        print("\nIncome Statement (Quarterly) - First 5 rows:")
        print(fundamentals["income_stmt_quarterly"].head())

    # Test 3: Earnings data
    print("\n" + "=" * 70)
    print("Test 3: Earnings History and Dates")
    print("=" * 70)

    earnings = fetcher.fetch_earnings(ticker)

    print("\nEarnings data:")
    for key, df in earnings.items():
        if not df.empty:
            print(f"\n{key}:")
            print(df.head())
        else:
            print(f"\n{key}: No data available")

    # Test 4: Institutional holders
    print("\n" + "=" * 70)
    print("Test 4: Institutional and Mutual Fund Holders")
    print("=" * 70)

    holders = fetcher.fetch_institutional_holders(ticker)

    if not holders["institutional_holders"].empty:
        print("\nTop Institutional Holders:")
        print(holders["institutional_holders"])
    else:
        print("\nInstitutional holders: No data available")

    if not holders["mutualfund_holders"].empty:
        print("\nTop Mutual Fund Holders:")
        print(holders["mutualfund_holders"])
    else:
        print("\nMutual fund holders: No data available")

    # Test 5: Check cached files
    print("\n" + "=" * 70)
    print("Test 5: Verify Caching")
    print("=" * 70)

    from pathlib import Path

    cache_dir = Path("data")

    print(f"\nJSON cache files for {ticker}:")
    json_files = list(cache_dir.glob(f"{ticker}_*.json"))
    for file in json_files:
        size_kb = file.stat().st_size / 1024
        print(f"  {file.name} ({size_kb:.1f} KB)")

    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
