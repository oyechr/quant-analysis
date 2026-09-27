# Roadmap: discovery & vetting companion

Goal: make `quant` a practical companion for **finding** candidate tickers, **vetting** a specific ticker, and **tracking** picks over time. Work is split into phases, done in order. This file is the handoff between sessions: read it first, and update the status table when a phase lands.

## Status

| Phase | Theme | Status |
|-------|-------|--------|
| 0 | Groundwork: compute/render split, cache expiry, local benchmarks, correctness fixes | Done |
| 1 | Find: `quant screen` | Done (sp500, sp100, nasdaq100, obx lists verified live; full command suite not yet run live) |
| 2 | Vet: `quant vet TICKER` | Next |
| 3 | Track: watchlist, score history, `quant changes` | Planned |
| 4 | Trust: price-only backtest, calibrate signal thresholds | Planned |
| 5 | Cleanup (do alongside the others) | Planned |

## How the code fits together (after Phases 0-1)

- `src/pipeline.py`: `analyze_ticker(ticker, fetcher, AnalysisOptions) -> AnalysisBundle`. Fetch, analyze, and score one ticker with **no file I/O**. `AnalysisBundle` has `.report` (the JSON-shaped dict), `.scoring` (`ScoringResult`), the analyzer objects, `.errors`, and `.freshness_warnings`. A per-run `_RunFetcher` makes sure each resource is fetched only once.
- `src/reporting/generator.py`: `ReportGenerator.generate(ticker, options, output_format) -> AnalysisBundle` runs the pipeline, then writes files. `generate_full_report(...)` is the old dict-returning wrapper, kept for callers (comparator, chat). `output_format="none"` writes nothing.
- `src/data_fetcher.py`: every resource has a cache expiry (`AnalysisConfig.cache_ttl_hours`). If a refresh fails, it falls back to the expired cache, including when yfinance returns an empty history. `fetcher.freshness(ticker)` records when each resource was fetched.
- `src/markets.py`: `benchmark_for(ticker)` maps an exchange suffix to its home index (`.OL` -> `OSEBX.OL`, `.L` -> `^FTSE`, ...). It can be overridden with `config.benchmark_by_suffix`.
- `src/screening/`: `universe.py` resolves universes (Nasdaq API / Wikipedia, 30-day cache, ticker files, `discover`). `screener.py` runs the two-stage screen: `FactorRanker` over everything, then `analyze_ticker` on the top N.
- `src/utils/concurrency.py`: `run_concurrently(fn, items, workers)` yields `(item, result, error)` and never raises.
- `src/utils/financial.py`: `trading_dates()` and `align_daily_returns()` handle cross-timezone and cached-UTC daily bars. Use them whenever two price series are compared.
- CLI: logging defaults to WARNING (`-v` for debug), and yfinance's own logger is silenced unless `-v`. Presets are exposed through `_config_option()`, parallelism through `_workers_option()`, and stale-data notices through `_echo_freshness_warnings()`.

### Conventions

- **Tests run offline.** `tests/conftest.py` provides `fake_market`, which monkeypatches `yfinance.Ticker` with a synthetic market (configurable prices, info, failures, and call counting) so the real fetcher, cache, analyzers, and scorer all run. Use `tmp_path` as the cache dir. `default_config` isolates tests from any local `config.json`.
- **Claude's shell cannot reach Yahoo/Wikipedia/Nasdaq** (TLS interception). For live checks, give the user exact commands to run and ask them to paste the output. Their local `data/` folder can be read afterwards for inspection.
- Before finishing a phase: `ruff check src tests`, `ruff format src tests`, `pytest tests -q`, update the README, and update this file.
- Yahoo units: `debtToEquity` is a percentage (150 = 1.5x). `risk_free_rate` is a decimal (0.04).

## Phase 2: `quant vet TICKER`

A one-screen verdict for deciding whether a ticker deserves a deeper look. It complements `report` (the full write-up saved to files) and does not replace it.

**Tasks**

1. **Red flags module** (`src/vetting/red_flags.py`). Checks the report dict and returns `[{severity, title, detail}]`, sorted by severity.
   - Beneish M-Score > -1.78 (possible earnings manipulation).
   - Altman Z in the distress zone.
   - Negative free cash flow in 2 or more of the last 3 years.
   - Share count dilution > 3%/yr (from the balance sheet or `sharesOutstanding` history).
   - Dividend not covered (payout > 100%, or FCF coverage < 1).
   - Interest coverage < 2.
   - Latest annual statements older than 15 months.
   - Low score confidence or data coverage < 60%.
   - Any `data_freshness.warnings`.
2. **Peer-relative valuation.** Today P/E is scored against fixed cutoffs (15/25/35 in `src/scoring/config.py::ValuationScoringParams`).
   - Peer set: `--peers T1,T2,...`, or automatic peers from the same `industry`. For automatic peers, look in the cached universes in `data/_universes/`, then in `data/*/cache/info.json`.
   - Compare P/E, forward P/E, EV/EBITDA, P/S, P/B, and FCF yield against the peer median. Show the percentile.
   - Add an option to the scorer so valuation can be scored against the sector or peer median. Keep the absolute cutoffs as the fallback when there are fewer than 4 peers.
   - `get_ticker_info` doesn't extract EV/EBITDA or `currentPrice` yet. Add `enterpriseToEbitda`, `currentPrice`, and `sharesOutstanding` in `DataFetcher.get_ticker_info`.
3. **Wire in the unused signals.**
   - `calculate_pead_signal(earnings_history, price_data)` in `src/analysis/fundamental.py:1246`.
   - `calculate_relative_strength(price_data, benchmark_data)` in `src/analysis/technical.py:766`, using the benchmark from `benchmark_for()`.
   - Add both to the pipeline report (e.g. `report["signals"]`) and show them in `vet`.
4. **13F ownership cross-reference.** From the cached `data/_discovery/edgar_13f/<CIK>.json` (see `Edgar13FSource`), list which tracked funds hold the ticker and their latest action (new/add/trim/exit). No network is needed if the cache exists; otherwise print a hint to run `quant discover`.
5. **"What would change the verdict".**
   - Fair value range from `valuation_analysis.monte_carlo_valuation.confidence_intervals` (`ci_10` ... `ci_90`, plus `probability_undervalued`) and DCF.
   - The price at which the valuation dimension would flip up or down one signal band.
   - Trade levels from `ScoringResult.trade_levels`.
6. **CLI `vet`.**
   - Sections in this order: header (name, sector, price, score/signal/confidence, preset), red flags, peer valuation table, signals, fund activity, fair value range, strengths/concerns, next steps.
   - `--peers`, `--config`, `--json`.
   - Uses `analyze_ticker` directly (no files written), except `--save`, which writes `data/<T>/reports/vet.json` and `vet.md`.
7. **`compare` improvements.** Show `identify_correlation_flags(corr)` (highly correlated pairs and hedges) and `calculate_risk_parity_weights(prices)` as a suggested-weights row (both in `src/comparison/comparator.py`).
8. **Chat.** Add red flags and peer context to `llm.build_brief_context` so `quant chat` sees them.

**Done when:** `quant vet EQNR.OL` and `quant vet AAPL --peers MSFT,GOOGL,META` render every section from live data. Each red-flag rule has an offline test using a synthetic report. The peer percentile maths is tested. The README is updated.

## Phase 3: Track

1. **Watchlist.** `watchlist.toml` in the repo root (gitignored, since it's personal). Each entry has a ticker, an optional one-line thesis, the date added, and an optional target/stop.
   - `quant watchlist add T --thesis "..."`, `quant watchlist rm T`, `quant watchlist ls`.
   - Add `quant screen ... --add-to-watchlist N` to add the top N results.
   - `watchlist` should also work as a universe name in `screen`.
2. **Score history.** Every `report`/`score`/`vet`/`screen` stage-2 run appends a row to `data/_history/scores.csv`: date, ticker, preset, composite, the four dimension scores, signal, price, and red-flag count. Deduplicate to one row per ticker, preset, and day.
3. **`quant changes`.** For the watchlist (or given tickers), refresh and show changes since the last history row: score delta, signal changes, new or resolved red flags, price vs target/stop, and upcoming earnings within 14 days. This replaces the polling loop in `watch`. Keep `watch` for intraday use, but point to `changes` for daily use.
4. **Chat context.** Include the ticker's score history (last N rows) so `quant chat` can answer "why did the score drop?"

**Done when:** add, change, and remove work with offline tests. After two runs on different days (simulate by editing history in a test), `changes` reports the deltas. The README is updated.

## Phase 4: Trust (backtest & calibration)

Price-only walk-forward test of the signals that can be computed point-in-time.

1. `src/backtest/`: for each month-end in the last N years and each ticker in a universe, compute the technical score, risk score, and factor-ranker momentum/low-vol using only data up to that date. Record the forward 1/3/6-month returns, both raw and relative to the benchmark.
2. Report: rank IC (Spearman) per signal and horizon, quintile spread (top minus bottom), and hit rate, with confidence intervals.
3. **Be explicit about the limit:** Yahoo's statements are not point-in-time (restated, and published with a lag), so the fundamental and valuation dimensions can't be backtested honestly this way. Label this in the output and the README.
4. **Calibrate.** Only a score of 50-65 counts as "Hold"; 49 is labelled "Sell" (`SignalThresholds` in `src/scoring/config.py`). Use the backtest to set the thresholds and preset weights, or to document that they are heuristics.
5. `quant backtest sp100 --years 5` prints the table and saves it to `data/_backtests/`.

**Done when:** the backtest runs offline on synthetic prices in tests, and live on sp100. The signal thresholds are either justified by results or documented as heuristics.

## Phase 5: Cleanup (do alongside the other phases)

- Split `src/reporting/generator.py` (~900 lines of Markdown formatting) into `reporting/markdown.py`.
- Turn `src/cli.py` into a package (`cli/__init__.py` plus one module per command group). Move table rendering out of the command functions.
- **27 tests skip** because they need `data/AAPL/reports/*.json` (gitignored). Generate a fixture report with the `fake_market` pipeline into `tests/fixtures/` and point `test_scorer.py`/`test_toon_serializer.py` at it.
- `FundamentalAnalyzer.calculate_all()` runs 3 times per report (JSON section, markdown, per-analysis JSON). Memoize it like `ValuationAnalyzer.analyze()`.
- Filters for market cap and volume mix currencies across exchanges (NOK vs USD). Convert with FX rates (`EURUSD=X`-style Yahoo symbols) if it matters.
- Make mypy blocking in CI once the backlog is cleared (currently `continue-on-error`).
- `examples/` duplicates the CLI. Keep only what documents the Python API.

## Starting a new session

Paste something like:

> Read docs/ROADMAP.md and start Phase 2. Follow its conventions (offline tests with the fake_market fixture; give me live commands to run since your shell can't reach Yahoo). Propose the design for red flags and peer selection before writing code.
