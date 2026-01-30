"""Test valuation markdown generation"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis import ValuationAnalyzer
from src.data_fetcher import DataFetcher
from datetime import datetime

def main():
    ticker = "GJF.OL"
    print(f"Testing valuation markdown generation for {ticker}...")
    
    # Fetch data
    fetcher = DataFetcher()
    info = fetcher.get_ticker_info(ticker)
    price_data = fetcher.fetch_ticker(ticker, period="1y")
    fundamentals = fetcher.fetch_fundamentals(ticker)
    earnings_data = fetcher.fetch_earnings(ticker)
    
    div_data = fetcher.fetch_dividends(ticker)
    dividends_df = div_data.get("dividends")
    dividends_series = None
    if dividends_df is not None and not dividends_df.empty:
        dividends_series = dividends_df.set_index("Date")["Dividends"]
    
    # Create analyzer
    analyzer = ValuationAnalyzer(
        ticker=ticker,
        ticker_info=info,
        price_data=price_data,
        fundamentals=fundamentals,
        earnings_data=earnings_data,
        dividends_data=dividends_series,
    )
    
    # Generate markdown
    md = analyzer.format_markdown()
    
    # Save to file
    output_dir = Path("data") / ticker / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "valuation_analysis.md"
    
    full_md = [f"# {ticker} - Valuation Analysis Report", "", 
               f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    full_md.extend(md)
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(full_md))
    
    print(f"✓ Markdown saved to: {output_file}")
    print(f"✓ Lines generated: {len(md)}")
    
    # Preview first 20 lines
    print("\nPreview:")
    print("=" * 60)
    for line in full_md[:20]:
        print(line)
    print("...")

if __name__ == "__main__":
    main()
