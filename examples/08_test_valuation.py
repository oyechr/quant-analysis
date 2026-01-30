"""
Test Valuation Analysis (UTF-8 safe version)
Tests DCF, DDM, dividend analysis, and earnings analysis
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis import ValuationAnalyzer
from src.data_fetcher import DataFetcher


def main(ticker: str = "GJF.OL"):
    """
    Test valuation analysis

    Args:
        ticker: Stock ticker symbol
    """
    print(f"\n{'='*60}")
    print(f"VALUATION ANALYSIS TEST: {ticker}")
    print(f"{'='*60}\n")

    # Initialize fetcher
    fetcher = DataFetcher()

    # Fetch data
    print("Fetching data...")
    info = fetcher.get_ticker_info(ticker)
    price_data = fetcher.fetch_ticker(ticker, period="1y")
    fundamentals = fetcher.fetch_fundamentals(ticker)
    earnings_data = fetcher.fetch_earnings(ticker)

    # Fetch dividends separately
    div_data = fetcher.fetch_dividends(ticker)
    dividends_df = div_data.get("dividends")

    # Extract dividend Series from DataFrame if it exists
    dividends_series = None
    if dividends_df is not None and not dividends_df.empty:
        dividends_series = dividends_df.set_index("Date")["Dividends"]

    # Create analyzer
    print("Running valuation analysis...\n")
    analyzer = ValuationAnalyzer(
        ticker=ticker,
        ticker_info=info,
        price_data=price_data,
        fundamentals=fundamentals,
        earnings_data=earnings_data,
        dividends_data=dividends_series,
    )

    # Run analysis
    results = analyzer.analyze()

    # Helper to format currency
    def fmt_curr(value, currency_code="USD"):
        """Format currency with proper symbol"""
        symbols = {
            "USD": "$",
            "CAD": "CA$",
            "EUR": "€",
            "GBP": "£",
            "NOK": "kr",
            "SEK": "kr",
            "DKK": "kr",
            "JPY": "¥",
        }
        symbol = symbols.get(currency_code, currency_code)
        return f"{symbol}{value:.2f}"

    # Display results
    print(f"\n{'='*60}")
    print("DCF VALUATION")
    print(f"{'='*60}")
    dcf = results["dcf_valuation"]
    if dcf.get("error"):
        print(f"ERROR: {dcf['error']}")
    else:
        curr = dcf.get("currency", "USD")
        print(f"Intrinsic Value: {fmt_curr(dcf.get('intrinsic_value_per_share', 0), curr)}")
        print(f"Current Price:   {fmt_curr(dcf.get('current_price', 0), curr)}")
        discount = dcf.get("discount_premium_pct", 0)
        if discount is not None:
            if discount < 0:
                print(f"Status:          UNDERVALUED by {abs(discount):.1f}%")
            else:
                print(f"Status:          OVERVALUED by {discount:.1f}%")
        print(f"\nAssumptions:")
        print(f"  FCF Growth:      {dcf['assumptions']['growth_rate_source']}")
        print(f"  Terminal Growth: {dcf.get('terminal_growth_rate', 0):.1f}%")
        print(f"  WACC:            {dcf.get('wacc_used', 0):.1f}%")

    print(f"\n{'='*60}")
    print("DDM VALUATION")
    print(f"{'='*60}")
    ddm = results["ddm_valuation"]
    if ddm.get("error"):
        print(f"ERROR: {ddm['error']}")
    else:
        curr = ddm.get("currency", "USD")
        print(f"Intrinsic Value: {fmt_curr(ddm.get('intrinsic_value_per_share', 0), curr)}")
        print(f"Current Price:   {fmt_curr(ddm.get('current_price', 0), curr)}")
        discount = ddm.get("discount_premium_pct", 0)
        if discount is not None:
            if discount < 0:
                print(f"Status:          UNDERVALUED by {abs(discount):.1f}%")
            else:
                print(f"Status:          OVERVALUED by {discount:.1f}%")

    print(f"\n{'='*60}")
    print("DIVIDEND ANALYSIS")
    print(f"{'='*60}")
    div = results["dividend_analysis"]
    if not div.get("pays_dividends"):
        print("Company does not pay dividends")
    else:
        curr = info.get("currency", "USD")
        print(f"Dividend Yield:        {div.get('dividend_yield', 0):.2f}%")
        print(f"Annual Dividend:       {fmt_curr(div.get('annual_dividend', 0), curr)}")
        print(f"Payout Ratio:          {div.get('payout_ratio', 0):.1f}%")
        if div.get("dividend_coverage_ratio"):
            print(f"Dividend Coverage:     {div['dividend_coverage_ratio']:.2f}x")
        print(f"Consecutive Years:     {div.get('consecutive_years', 0)}")
        print(
            f"Sustainability:        {div.get('sustainability_score', 0)}/100 ({div.get('sustainability_rating', 'N/A')})"
        )

    print(f"\n{'='*60}")
    print("EARNINGS ANALYSIS")
    print(f"{'='*60}")
    earn = results["earnings_analysis"]
    curr = info.get("currency", "USD")
    if earn.get("current_eps"):
        print(f"Current EPS (TTM):     {fmt_curr(earn['current_eps'], curr)}")
    if earn.get("forward_eps"):
        print(f"Forward EPS:           {fmt_curr(earn['forward_eps'], curr)}")
    if earn.get("eps_growth_1y") is not None:
        print(f"EPS Growth (1Y):       {earn['eps_growth_1y']:+.1f}%")
    if earn.get("eps_growth_3y_cagr") is not None:
        print(f"EPS Growth (3Y CAGR):  {earn['eps_growth_3y_cagr']:+.1f}%")
    if earn.get("trend"):
        print(f"Trend:                 {earn['trend']}")

    # Earnings quality
    quality = earn.get("earnings_quality", {})
    if quality.get("assessment"):
        print(f"\nEarnings Quality:      {quality['assessment']}")
        print(f"Quality Score:         {quality.get('score', 0)}/100")
        metrics = quality.get("metrics", {})
        if "cash_flow_to_earnings_ratio" in metrics:
            print(f"CF/NI Ratio:           {metrics['cash_flow_to_earnings_ratio']:.2f}x")
        if "accruals_pct" in metrics:
            print(f"Accruals:              {metrics['accruals_pct']:.1f}%")

    # Save full results to JSON
    output_path = Path(__file__).parent.parent / "data" / ticker / "reports"
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / "valuation_analysis.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Full results saved to: {output_file}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else "GJF.OL"
    main(ticker)
