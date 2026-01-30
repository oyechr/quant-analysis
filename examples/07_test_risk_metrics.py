"""
Example: Test Risk Metrics
Demonstrates calculating risk and performance metrics
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis import RiskMetrics
from src.data_fetcher import DataFetcher


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="Calculate risk and performance metrics")
    parser.add_argument(
        "ticker", nargs="?", default="EXE.TO", help="Stock ticker symbol (default: EXE.TO)"
    )
    parser.add_argument(
        "--period",
        default="1y",
        help="Data period (default: 1y). Options: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Risk Metrics Analysis")
    print("=" * 70)

    # Initialize
    fetcher = DataFetcher()
    risk = RiskMetrics()

    ticker = args.ticker.upper()
    period = args.period

    print(f"\nFetching data for {ticker} ({period})...")
    price_data = fetcher.fetch_ticker(ticker, period=period)

    if price_data is None or price_data.empty:
        print(f"❌ Failed to fetch data for {ticker}")
        return

    print(f"✓ Loaded {len(price_data)} trading days")

    # Calculate all metrics
    print("\nCalculating risk metrics...")
    metrics = risk.calculate_all_metrics(price_data)

    # Display results
    print("\n" + "=" * 70)
    print("RETURNS ANALYSIS")
    print("=" * 70)

    if "returns" in metrics and metrics["returns"]:
        returns = metrics["returns"]
        print(f"\nDaily Returns:")
        print(f"  Mean:              {returns.get('daily_mean', 0):.4%}")
        print(f"  Std Dev:           {returns.get('daily_std', 0):.4%}")
        print(f"  Min (worst day):   {returns.get('daily_min', 0):.4%}")
        print(f"  Max (best day):    {returns.get('daily_max', 0):.4%}")

        print(f"\nPeriod Performance:")
        print(f"  Cumulative Return: {returns.get('cumulative_return', 0):.2%}")
        print(f"  Annualized Return: {returns.get('annualized_return', 0):.2%}")

        print(f"\nTrading Statistics:")
        print(f"  Total Days:        {returns.get('total_trading_days', 0)}")
        print(f"  Positive Days:     {returns.get('positive_days', 0)}")
        print(f"  Negative Days:     {returns.get('negative_days', 0)}")
        print(f"  Win Rate:          {returns.get('win_rate', 0):.2%}")
    else:
        print("\n⚠️  Returns data not available")

    print("\n" + "=" * 70)
    print("VOLATILITY ANALYSIS")
    print("=" * 70)

    if "volatility" in metrics and metrics["volatility"]:
        vol = metrics["volatility"]
        print(f"\nVolatility Metrics:")
        print(f"  Daily Volatility:      {vol.get('daily_volatility', 0):.4%}")
        print(f"  Annualized Volatility: {vol.get('annualized_volatility', 0):.2%}")
        print(f"  Downside Deviation:    {vol.get('downside_deviation', 0):.2%}")
    else:
        print("\n⚠️  Volatility data not available")

    print("\n" + "=" * 70)
    print("RISK-ADJUSTED RETURNS")
    print("=" * 70)

    sharpe = metrics.get("sharpe_ratio", 0)
    sortino = metrics.get("sortino_ratio", 0)

    print(f"\nSharpe Ratio:  {sharpe:.2f}")
    if sharpe > 1:
        print("  → Good risk-adjusted performance")
    elif sharpe > 0:
        print("  → Positive but modest risk-adjusted return")
    else:
        print("  → Underperforming risk-free rate")

    print(f"\nSortino Ratio: {sortino:.2f}")
    if sortino > sharpe:
        print("  → Better downside risk profile than overall volatility suggests")
    print("  (Higher is better - focuses on downside risk)")

    print("\n" + "=" * 70)
    print("DRAWDOWN ANALYSIS")
    print("=" * 70)

    if "drawdown" in metrics and metrics["drawdown"]:
        dd = metrics["drawdown"]
        print(f"\nDrawdown Metrics:")
        print(f"  Maximum Drawdown:  {dd.get('max_drawdown', 0):.2%}")
        print(f"  Max DD Date:       {dd.get('max_drawdown_date', 'N/A')}")
        print(f"  Current Drawdown:  {dd.get('current_drawdown', 0):.2%}")
        print(f"  Days Since Peak:   {dd.get('days_since_peak', 0)}")
        if dd.get("recovery_days"):
            print(f"  Recovery Time:     {dd.get('recovery_days')} days")
        print(f"  At Peak:           {'Yes' if dd.get('is_recovered') else 'No'}")
    else:
        print("\n⚠️  Drawdown data not available")

    print("\n" + "=" * 70)
    print("MARKET RISK (vs Benchmark)")
    print("=" * 70)

    if "market_risk" in metrics and metrics["market_risk"]:
        mr = metrics["market_risk"]
        print(f"\nBeta & Alpha:")
        print(f"  Benchmark:         {mr.get('benchmark', 'N/A')}")
        print(f"  Beta:              {mr.get('beta', 0):.2f}")
        if mr.get("beta", 0) > 1:
            print("    → More volatile than market")
        elif mr.get("beta", 0) < 1:
            print("    → Less volatile than market")
        else:
            print("    → Moves with market")
        print(f"  Alpha:             {mr.get('alpha', 0):.2%}")
        if mr.get("alpha", 0) > 0:
            print("    → Outperforming benchmark (risk-adjusted)")
        print(f"  Correlation:       {mr.get('correlation', 0):.2f}")
        print(f"  R-squared:         {mr.get('r_squared', 0):.2%}")
    else:
        print("\n⚠️  Market risk data not available")

    print("\n" + "=" * 70)
    print("TAIL RISK (Value at Risk)")
    print("=" * 70)

    if "var_95" in metrics and metrics["var_95"]:
        var95 = metrics["var_95"]
        print(f"\n95% Confidence Level:")
        print(f"  VaR (Historical):  {var95.get('var_historical', 0):.2%}")
        print(f"  CVaR (Expected):   {var95.get('cvar_historical', 0):.2%}")
        print(f"  VaR (Parametric):  {var95.get('var_parametric', 0):.2%}")
        print("  → 5% chance of losing more than VaR in a day")

    if "var_99" in metrics and metrics["var_99"]:
        var99 = metrics["var_99"]
        print(f"\n99% Confidence Level:")
        print(f"  VaR (Historical):  {var99.get('var_historical', 0):.2%}")
        print(f"  CVaR (Expected):   {var99.get('cvar_historical', 0):.2%}")
        print("  → 1% chance of losing more than VaR in a day")

        print(f"\nWorst Historical Day: {var99.get('worst_day', 0):.2%}")

    print("\n" + "=" * 70)
    print("Risk Metrics Test Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
