"""
Example: Generate Comprehensive Reports
Demonstrates using ReportGenerator to create JSON and Markdown reports
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reporting import ReportGenerator


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate comprehensive stock analysis reports")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g., AAPL, MSFT, TSLA)")
    parser.add_argument(
        "--period",
        default="1y",
        help="Data period (default: 1y). Options: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max",
    )
    parser.add_argument(
        "--no-technical",
        action="store_true",
        help="Exclude technical analysis from report",
    )
    parser.add_argument(
        "--no-fundamental",
        action="store_true",
        help="Exclude fundamental analysis from report",
    )
    parser.add_argument(
        "--no-risk",
        action="store_true",
        help="Exclude risk analysis from report",
    )
    parser.add_argument("--no-cache", action="store_true", help="Fetch fresh data (ignore cache)")
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="both",
        help="Output format (default: both)",
    )

    args = parser.parse_args()

    # Initialize report generator
    generator = ReportGenerator(output_dir="data")

    print("=" * 70)
    print("Generating Comprehensive Stock Reports")
    print("=" * 70)

    # Generate report with user-specified options
    ticker = args.ticker.upper()
    print(f"\nGenerating report for {ticker}...")

    report_data = generator.generate_full_report(
        ticker=ticker,
        period=args.period,
        output_format=args.format,
        use_cache=not args.no_cache,
        include_technical=not args.no_technical,
        include_fundamental=not args.no_fundamental,
        include_risk=not args.no_risk,
    )

    print(f"\n✓ Report generated for {ticker}")
    if args.format in ["both", "json"]:
        print(f"  - JSON: data/{ticker}/reports/full_report.json")
    if args.format in ["both", "markdown"]:
        print(f"  - Markdown: data/{ticker}/reports/report.md")
    if not args.no_technical:
        print(f"  - Technical Analysis: data/{ticker}/reports/technical_analysis.md + .json")
    if not args.no_fundamental:
        print(f"  - Fundamental Analysis: data/{ticker}/reports/fundamental_analysis.md + .json")
    if not args.no_risk:
        print(f"  - Risk Analysis: data/{ticker}/reports/risk_analysis.md + .json")

    # Summary
    print("\n" + "=" * 70)
    print("Report Generation Complete!")
    print("=" * 70)
    print(f"\nTicker: {ticker}")
    print(f"Period: {args.period}")
    print(f"Cache: {'Used' if not args.no_cache else 'Bypassed'}")
    print("\nView reports:")
    print("  - JSON files: Machine-readable, complete data")
    print("  - Markdown files: Human-readable, formatted (right-click → 'Open Preview')")
    print(f"\nFiles saved in: data/{ticker}/reports/")
    print("\nUsage examples:")
    print("  python examples\\04_generate_report.py AAPL")
    print("  python examples\\04_generate_report.py TSLA --period 2y")
    print("  python examples\\04_generate_report.py MSFT --no-cache --format markdown")


if __name__ == "__main__":
    main()
