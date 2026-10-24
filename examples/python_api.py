"""
Using quant-analysis from Python.

The `quant` CLI covers day-to-day use. These are the entry points behind it,
for notebooks and scripts:

1. analyze_ticker: fetch, analyze and score one ticker (writes no files)
2. the score and the analyzers behind each dimension
3. vet_ticker: what `quant vet` shows, as data
4. Screener: factor-rank a list of tickers, then fully score the best

Run from the repo root (fetches from Yahoo Finance, cached under data/):

    python examples/python_api.py [TICKER]
"""

import sys

from src.data_fetcher import DataFetcher
from src.pipeline import AnalysisOptions, analyze_ticker
from src.scoring import ScoringConfig
from src.screening import Screener, format_screen_table
from src.vetting import render_text, vet_ticker


def main(ticker: str = "AAPL") -> None:
    fetcher = DataFetcher(cache_dir="data")  # the same cache the CLI uses

    # 1. One ticker, end to end. include_context=False skips holders, analyst
    #    ratings and news, which the score doesn't use.
    options = AnalysisOptions(include_context=False, scoring_config=ScoringConfig.value_investor())
    bundle = analyze_ticker(ticker, fetcher=fetcher, options=options)
    if bundle.errors:
        print(f"Partial data for {ticker}: {bundle.errors}")
    if bundle.scoring is None:
        sys.exit(f"Could not score {ticker}")

    # 2. The composite score, then a number from each analyzer.
    #    bundle.report is the same dict `quant report` saves as full_report.json.
    print(bundle.scoring.format_scorecard())
    if bundle.technical:
        print("Signals:", bundle.report["technical_analysis"]["signals"])
    if bundle.fundamental:
        quality = bundle.fundamental.calculate_all()["quality_scores"]
        print("Piotroski F-Score:", quality["piotroski_f"], "/ 9")
    if bundle.risk:
        _, metrics, _ = bundle.risk
        print("Sharpe ratio:", metrics["sharpe_ratio"], "| beta:", metrics["market_risk"]["beta"])
    if bundle.valuation:
        dcf = bundle.valuation.analyze()["dcf_valuation"]
        print("DCF value per share:", dcf.get("intrinsic_value_per_share"))

    # 3. The vet verdict: red flags, peer valuation, fair value range, ...
    vet = vet_ticker(ticker, fetcher=fetcher, peers=["MSFT", "GOOGL"])
    print("Red flags:", [flag.title for flag in vet.red_flags] or "none")
    print(render_text(vet.to_dict(), brief=True))

    # 4. Screen a handful of tickers: rank all of them, fully score the top 3
    screener = Screener(fetcher=fetcher)
    result = screener.run([ticker, "MSFT", "GOOGL", "NVDA", "JNJ"], top_n=3)
    print(format_screen_table(result))
    best = [c.ticker for c in result.scored if c.scoring]
    print("Best by composite score:", best)


if __name__ == "__main__":
    main(*sys.argv[1:2])
