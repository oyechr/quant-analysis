# Development

For working on the code. Using the tool is covered in the [README](../README.md); the plan and the design notes behind each phase are in [ROADMAP.md](ROADMAP.md).

## Setup and checks

```bash
pip install -e ".[all,dev]"
```

CI (`.github/workflows/ci.yml`) runs these four, and all of them block a merge:

```bash
ruff check src tests
ruff format --check src tests
mypy src --ignore-missing-imports
pytest tests -q
```

Chain them with `&&` locally, so a failure stops the rest. `ruff check --fix` and `ruff format` fix most lint and format issues. mypy skips untyped libraries (yfinance, finta, toon, seaborn, matplotlib); `pandas-stubs` and `types-requests` come with the `dev` extra.

## Conventions

- **Tests run offline:**
  - The `fake_market` fixture in `tests/conftest.py` replaces `yfinance.Ticker`, `Industry` and `Sector` with a synthetic market. You can configure its prices, info, statements and failures, and it counts calls. With it, the real fetcher, cache, analyzers and scorer all run without the network.
  - Use `tmp_path` as the cache dir. `default_config` keeps tests away from any local `config.json`.
  - `sample_data_dir` builds full reports for a few tickers once per session.
- **Live checks:** run against Yahoo by hand, with the commands in the README. A refactor is checked with before/after snapshots of the help pages, the CLI output and the report files.
- **Private data stays out of git:**
  - Never put real holdings, amounts or account numbers in committed files: code, tests, docs or CLI help.
  - `portfolio/`, `watchlist.toml`, `config.json` and `data/` are gitignored.
  - Tests use made-up tickers and amounts.
- **Yahoo units:** `debtToEquity` is a percentage (150 = 1.5x), and `risk_free_rate` is a decimal (0.04). Market cap is in the major currency unit, even for a GBp listing.
- **Cache version:** bump `INFO_CACHE_VERSION` in `data_fetcher.py` whenever `get_ticker_info` gains a field, so older cached info is refetched.
- **Style:** match the surrounding code. Decision rules are explicit, testable functions with their thresholds as module constants (see `vetting/red_flags.py`, `portfolio/review.py::decide_action` and `portfolio/rebalance.py::propose_trades`). Every rule gets a test with synthetic data.

## How the code fits together

- **`pipeline.analyze_ticker(ticker, fetcher, options) -> AnalysisBundle`** fetches, analyzes and scores one ticker, with no file I/O.
  - The bundle holds `.report` (the JSON-shaped dict), `.scoring` (a `ScoringResult`), the analyzer objects, `.errors` and `.freshness_warnings`.
  - Statements are converted into the listing currency here, once.
- **`data_fetcher.DataFetcher`** has a cache expiry per resource. When a refresh fails, it falls back to the expired cache. `fetcher.freshness(ticker)` records when each resource was fetched.
- **`markets.benchmark_for(ticker)`** maps an exchange suffix to its home index. Use `utils.financial.trading_dates` / `align_daily_returns` whenever two price series from different exchanges are compared.
- **`reporting.ReportGenerator`** runs the pipeline, then writes the report files (`reporting/markdown.py` builds report.md).
- **`vetting.vet_ticker`** is the pipeline plus peers, red flags, 13F activity and the verdict. `VetResult.base_scoring` keeps the score before the peer rescale, and that is what the score history stores.
- **`portfolio`:**
  - `review_portfolio` vets every holding, values it in the base currency, and calls `exposure.measure_exposure` and `targets.target_weights`.
  - `rebalance.propose_trades` turns the review into trades.
  - `review.MarketData` memoizes FX rates and the 2-year closes for a run.
- **`screening.Screener`** ranks a universe with `discovery.FactorRanker`, then runs `analyze_ticker` on the top N.
- **`tracking`** holds the watchlist, the score history (`data/_history/scores.csv`) and `track_changes`.
- **`backtest.run_backtest`** scores price-only signals at past month-ends; `stats` computes IC, spreads and bands with Newey-West errors.
- **Concurrency:** `utils.concurrency.run_concurrently(fn, items, workers)` yields `(item, result, error)` and never raises.
- **Rendering:** each command's output is built as `vetting.render` sections (text and Markdown from the same `Section` list).

## Project structure

```
quant-analysis/
+-- src/
|   +-- cli/                         # `quant` group + one module per command group
|   |   +-- analyze.py               # report, score, vet, compare, watch
|   |   +-- find.py                  # screen, discover
|   |   +-- chat.py                  # chat
|   |   +-- portfolio.py             # import-portfolio, review, rebalance
|   |   +-- track.py                 # watchlist, changes
|   |   +-- backtest.py              # backtest
|   |   +-- common.py                # shared options and helpers
|   +-- data_fetcher.py              # Yahoo Finance fetching, cache with expiry
|   +-- pipeline.py                  # fetch -> analyze -> score for one ticker
|   +-- markets.py                   # exchange suffix -> benchmark index
|   +-- config.py                    # config.json settings
|   +-- llm.py                       # chat: providers, context building
|   +-- analysis/
|   |   +-- technical.py             # indicators (finta)
|   |   +-- fundamental.py           # growth, margins, Piotroski, Altman, Beneish
|   |   +-- valuation.py             # DCF, reverse DCF, Monte Carlo, DDM, earnings
|   |   +-- risk.py                  # volatility, ratios, drawdowns, VaR, beta
|   +-- scoring/
|   |   +-- config.py                # weights, thresholds, presets
|   |   +-- dimensions.py            # the four dimension scorers
|   |   +-- scorer.py                # StockScorer: composite, signal, strengths/concerns
|   |   +-- trade_levels.py          # entry, stop and target levels
|   +-- vetting/
|   |   +-- red_flags.py             # one function per rule
|   |   +-- peers.py                 # Yahoo industry/sector peers, percentiles
|   |   +-- ownership.py             # 13F fund activity from the discover cache
|   |   +-- verdict.py               # fair value range, signal flip prices
|   |   +-- vet.py                   # vet_ticker(), the verdict summary
|   |   +-- render.py                # sections -> text / Markdown
|   +-- portfolio/
|   |   +-- nordnet.py               # Nordnet exports -> portfolio.csv
|   |   +-- review.py                # review_portfolio(), decide_action()
|   |   +-- exposure.py              # weekly base-currency risk, beta, factor tilts
|   |   +-- targets.py               # equal-risk-contribution targets, targets.toml
|   |   +-- rebalance.py             # propose_trades(), accounts, AF tax
|   |   +-- render.py                # review and rebalance output
|   +-- screening/
|   |   +-- universe.py              # index lists, ticker files, discover picks
|   |   +-- screener.py              # two-stage screen
|   +-- discovery/
|   |   +-- models.py                # holdings, portfolios, signals
|   |   +-- analyzer.py              # cross-portfolio patterns
|   |   +-- enrichment.py            # CUSIP -> ticker, sector/industry
|   |   +-- factor_ranking.py        # cross-sectional factor ranking
|   |   +-- render.py                # discover output
|   |   +-- sources/                 # pluggable sources (base.py, edgar_13f.py)
|   +-- tracking/
|   |   +-- watchlist.py             # watchlist.toml
|   |   +-- history.py               # score history
|   |   +-- changes.py               # what moved since the last run
|   +-- backtest/
|   |   +-- engine.py                # point-in-time signals, forward returns
|   |   +-- stats.py                 # IC, quintile spread, hit rate, bands
|   |   +-- render.py                # output and saving
|   +-- comparison/
|   |   +-- comparator.py            # compare, correlations, inverse-volatility weights
|   |   +-- formatters.py            # tables, heatmap
|   +-- reporting/
|   |   +-- generator.py             # report files
|   |   +-- markdown.py              # report.md
|   |   +-- sections.py              # report sections
|   +-- utils/                       # concurrency, fx, financial maths, serialization, TOON
+-- examples/
|   +-- python_api.py                # the Python API, end to end (see examples/README.md)
+-- tests/                           # one test_*.py per area; conftest.py has the fake market
+-- docs/
    +-- ROADMAP.md                   # phases, status, design notes
    +-- DEVELOPMENT.md               # this file
```

## Python API

The CLI is the main interface. For notebooks and scripts, the same entry points are available directly; [examples/python_api.py](../examples/python_api.py) runs them end to end.

```python
from src.pipeline import AnalysisOptions, analyze_ticker
from src.scoring import ScoringConfig

# Compute only (no files written)
bundle = analyze_ticker("AAPL", options=AnalysisOptions(scoring_config=ScoringConfig.value_investor()))
print(f"{bundle.scoring.composite_score:.0f}/100  ({bundle.scoring.signal})")

# Compute and write report files
from src.reporting import ReportGenerator
report_data = ReportGenerator(output_dir="data").generate_full_report("AAPL", period="1y")

# Screen a universe
from src.screening import Screener, ScreenFilters, resolve_universe
universe = resolve_universe(["sp100"])
result = Screener().run(universe.tickers, ScreenFilters(min_market_cap=100e9), top_n=10)
for c in result.scored:
    print(c.ticker, c.scoring.composite_score, c.factor_rank)

# Vet one ticker
from src.vetting import render_text, vet_ticker
vet = vet_ticker("AAPL", peers=["MSFT", "GOOGL", "META"])
print(render_text(vet.to_dict()))

# Review a portfolio file and propose trades
from pathlib import Path
from src.portfolio import load_portfolio, load_targets, rebalance_portfolio, review_portfolio
holdings, _ = load_portfolio(Path("portfolio/portfolio.csv"))
settings = load_targets(Path("portfolio/targets.toml"))
review = review_portfolio(holdings, targets=settings)
proposal = rebalance_portfolio(review, ["AAPL"], settings, cash=10_000)
print(proposal.to_dict()["trades"])
```
