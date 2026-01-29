"""
Example: Generate Comprehensive Reports
Demonstrates using ReportGenerator to create JSON and Markdown reports
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.report_generator import ReportGenerator


def main():
    # Initialize report generator
    generator = ReportGenerator(output_dir="data")

    print("=" * 70)
    print("Generating Comprehensive Stock Reports")
    print("=" * 70)

    # Example 1: Generate full report (both JSON and Markdown)
    ticker = "EXE.TO"
    print(f"\nGenerating report for {ticker}...")

    report_data = generator.generate_full_report(
        ticker=ticker,
        period="1y",  # Use 1y to share cache with technical analysis
        output_format="both",  # Creates both JSON and Markdown
        use_cache=True,
    )

    print(f"\n✓ Report generated for {ticker}")
    print(f"  - JSON: data/{ticker}/reports/full_report.json")
    print(f"  - Markdown: data/{ticker}/reports/report.md")

    # Example 2: Generate report with technical analysis
    print("\n" + "=" * 70)
    print("Generating Report with Technical Analysis")
    print("=" * 70)

    print(f"\nGenerating enhanced report for {ticker}...")
    report_data = generator.generate_full_report(
        ticker=ticker,
        period="1y",  # Same period - reuses cache from Example 1
        output_format="both",
        use_cache=True,
        include_technical=True,  # Enable technical analysis
        include_fundamental=True,  # Enable fundamental analysis
    )

    print(f"\n✓ Enhanced report generated for {ticker}")
    print(f"  - JSON: data/{ticker}/reports/full_report.json")
    print(f"  - Markdown: data/{ticker}/reports/report.md")
    print(f"  - Technical Analysis: data/{ticker}/reports/technical_analysis.md + .json")
    print(f"  - Fundamental Analysis: data/{ticker}/reports/fundamental_analysis.md + .json")

    # # Example 3: Generate multiple reports
    # print("\n" + "=" * 70)
    # print("Generating Reports for Multiple Tickers")
    # print("=" * 70)
    #
    # tickers = ["MSFT", "GOOGL", "NVDA"]
    # for ticker in tickers:
    #     print(f"\nGenerating report for {ticker}...")
    #     generator.generate_full_report(
    #         ticker=ticker,
    #         period="1mo",
    #         output_format="both"
    #     )
    #     print(f"  ✓ {ticker} report complete")

    # # Example 3: Generate only Markdown (for reading)
    # print("\n" + "=" * 70)
    # print("Generating Markdown-Only Report")
    # print("=" * 70)
    #
    # ticker = "TSLA"
    # print(f"\nGenerating Markdown report for {ticker}...")
    # generator.generate_full_report(
    #     ticker=ticker,
    #     period="1m",
    #     output_format="markdown"  # Only creates .md file
    # )
    # print(f"  ✓ Markdown report: data/{ticker}_report.md")
    # print(f"  (Open in VS Code for formatted preview)")

    # Summary
    print("\n" + "=" * 70)
    print("All Reports Generated!")
    print("=" * 70)
    print("\nView reports:")
    print("  - JSON files: Machine-readable, complete data")
    print("  - Markdown files: Human-readable, formatted (right-click → 'Open Preview')")
    print("\nFiles saved in: data/<TICKER>/")


if __name__ == "__main__":
    main()
