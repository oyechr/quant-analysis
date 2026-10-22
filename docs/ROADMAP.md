# Roadmap: discovery & vetting companion

Goal: make `quant` a practical companion for **finding** candidate tickers, **vetting** a specific ticker, **reviewing** the portfolio you hold, and **tracking** picks over time. Work is split into phases, done in order. This file is the handoff between sessions: read it first, and update the status table when a phase lands.

## Status

| Phase | Theme | Status |
|-------|-------|--------|
| 0 | Groundwork: compute/render split, cache expiry, local benchmarks, correctness fixes | Done |
| 1 | Find: `quant screen` | Done (sp500, sp100, nasdaq100, obx lists verified live; full command suite not yet run live) |
| 2 | Vet: `quant vet TICKER` | Done (live-checked on EQNR.OL and AAPL, 2026-09-28) |
| 2b | Vet follow-ups: established data sources, verdict summary | Done; the live run showed Yahoo's micro-cap peer lists and mixed-currency ratios, both handled but over-engineered (see 2c) |
| 2c | Simplify peers and currency handling (standard practice) | Done (live-checked on AAPL, EQNR.OL and EQNR.OL --peers AKRBP.OL,VAR.OL, 2026-09-28) |
| 2d | DCF fix: two-stage fade, standard WACC, reverse DCF | Done (live-checked on AAPL and EQNR.OL, 2026-10-22) |
| 3 | Review: portfolio file -> exit / review / trim / hold / add advice | Done (live run on the user's portfolio, 2026-10-22; tuning after first use) |
| 4 | Track: watchlist, score history, `quant changes` | Done (first live `changes` run OK, 2026-10-22; second-day deltas not yet seen live) |
| 5 | Trust: price-only backtest, calibrate signal thresholds | Backtest built offline (2026-10-22); live sp100 run and calibration pending |
| 6 | Cleanup (do alongside the others) | Planned |

## Current state and next session (updated 2026-10-22)

Everything through 2d and `quant import-portfolio` is committed and pushed (d885f5b). Phase 3 (`quant review`) is committed on `main` (ec9e262, not pushed). Phase 4 (Track) is on `main` (0cfc2f9, not pushed). The FCF-yield scoring fix and the Phase 5 backtest were built on 2026-10-22 and are uncommitted; all tests pass offline (531 passed, 27 skipped). Claude's shell still can't reach Yahoo (TLS interception in the sandbox), so live checks are for the user to run. Next: the user runs `quant backtest sp100` (and `obx`), then Phase 5 task 4: calibrate or document the signal thresholds from those results. Still open from Phase 4: seeing the second-day `changes` deltas live.

**Portfolio input:** Nordnet's API is closed to retail customers (paid partner access only), and there is no API code in this repo. The supported input is the holdings export downloaded from Nordnet's web app, one file per account, combined with `quant import-portfolio`. Rerun the import whenever holdings change.

**Next session, in order:**

1. **2d live check: done (2026-10-22).** AAPL: DCF $91, price $348; the price implies +33% starting growth. EQNR.OL: DCF 235 NOK, price 432; implies +2.4%. Both match the offline numbers. EQNR's starting growth hits the -10% floor (the known cyclical-FCF limit), and its DDM (69 NOK) means little.
2. **Portfolio input confirmed (2026-10-22).** Every ticker was verified against Yahoo, and the accounts are labelled ASK and AF. Nordnet's 2026 export ("Beholdningstabell eksport, kontono. N, date.csv", name column "Handel") is now supported alongside the old one. Funds that Yahoo lists under Morningstar IDs (`0P...`) can be mapped like any ticker.
3. **Phase 3 first live run (2026-10-22).** About a third of the holdings came out as Exit, mostly on one model-based red flag. Fixes:
   - **Altman Z bug:** X4 was market cap / total *assets* instead of / total *liabilities*. That pulled every Z down, so companies with Z well into the safe zone (7 to 17) read as distressed. There is now a formula test (`tests/test_quant_methods.py::TestAltmanZ`).
   - **Utilities:** the Altman flag now skips them, as it does financials, since Altman's samples excluded both.
   - **Bad price bars:** Yahoo sometimes returns a bar with Open/High/Low = 0 (seen on a mutual fund's NAV series). `data_fetcher.clean_price_bars` now cleans fresh and cached prices: a non-positive Open/High/Low takes the Close, and a bar with no positive Close is dropped. This fixed a division by zero in support/resistance.
   - **`None` from yfinance:** for earnings dates of funds and new listings, `_fetch_resource` now turns `None` into an empty frame.
   - **Financials:** the negative-FCF flag and the FCF test for dividend cover now skip banks and insurers (their payout ratio is still checked), as the Altman and interest-cover rules already did. The "Only n/8 Beneish components" message is now info-level, not a warning.
   - **Exit rule (the user's choice):** Exit now needs a Sell or Strong Sell signal. A high-severity red flag with a Hold or Buy signal becomes the new **Review** action ("look into the flag before selling"), because Altman and Beneish have known false positives: large investment-grade telecoms read as distressed on Altman, and acquisitive companies trip Beneish. `vet` still says Pass for these.
   - **Follow-ups (done 2026-10-22):**
     - **Beneish** is skipped when sales more than tripled (`BENEISH_MAX_SGI` 3.0 in `analysis/fundamental.py`; Beneish's manipulators averaged 1.6). From a near-zero base the score ran into the hundreds.
     - **Banks and insurers in the score:** `scoring.dimensions.is_financial(info)` drops the inputs built on cash flow. That means the FCF DCF and the cash-backed part of Earnings Quality in valuation, and Altman, Beneish and Accruals in fundamentals. They're judged on Piotroski, growth, ROE, P/E, PEG, dividends and earnings beats. `vet`'s fair value table leaves out the DCF and Monte Carlo for them (it keeps analyst targets and the DDM) and says why. The red flags use the same sector list.
     - **Risk-parity targets:** kept. On the live portfolio, equal weight (1/N) would only have changed one thing, wrongly trimming a broad ETF, and inverse-volatility capped at 0.5-2x of 1/N changed nothing.

**Portfolio input as built:**
- `src/portfolio/nordnet.py` provides `read_nordnet_holdings`, `load_ticker_map`, `combine_holdings` and `write_portfolio`. The CLI command is `quant import-portfolio EXPORTS... [--map] [--out] [--label N=NAME] [--verify]`.
- Nordnet's holdings export ("aksjelister") is UTF-16 and tab-separated, with decimal commas and Norwegian headers: Navn, Valuta, Antall, GAV (average cost per share in the instrument currency), Siste kurs, Verdi, Verdi NOK, Avkast. It has no ISIN or ticker, so names are mapped with `portfolio/tickers.csv`.
- Output format is `portfolio/portfolio.csv` with columns `ticker,name,account,shares,cost_basis,currency`: one row per account and instrument. The same stock can appear in two accounts, and it stays as two rows because tax treatment differs, so Phase 3 should aggregate by ticker for weights.
- The account defaults to the number in the file name.
- `/portfolio/` and `aksjelister_*.csv` are gitignored. Tests use synthetic exports written in `tmp_path` (`tests/test_portfolio.py`). Never put real holdings, account numbers or amounts in committed files, including this one.
- The user's holdings span many listing currencies and include an ETF, so Phase 3 must handle mixed currencies. Value the holdings in NOK using `utils/fx.usd_per_unit` / `conversion_rate`, and handle the ETF, which has no fundamentals (score it on technicals and risk only, or skip it with a note).

**2d DCF fix as built** (`src/analysis/valuation.py`):
- `dcf_enterprise_value()` is one vectorized core shared by DCF, Monte Carlo and the reverse DCF `implied_growth()`. Starting FCF growth is the 3-year FCF CAGR clamped to `GROWTH_BOUNDS` (-10%, +20%). It fades linearly to `TERMINAL_GROWTH` (2.5%) over `PROJECTION_YEARS` (10), followed by a Gordon terminal value.
- Discount rate: WACC = E/V x cost of equity + D/V x cost of debt x (1 - tax).
  - Cost of equity uses CAPM: `config.risk_free_rate` + a Blume-adjusted beta (0.67 x raw + 0.33) x `config.equity_risk_premium` (new, 5%). A missing or negative Yahoo beta falls back to 1.
  - Cost of debt is interest over debt, at least the risk-free rate. Tax is "Tax Rate For Calcs".
  - The old version used an 8% premium, raw beta and no debt.
- Net debt is Total Debt minus Cash, Cash Equivalents and Short Term Investments, from the latest converted balance sheet. Before this, net debt was always 0, because `totalDebt`/`totalCash` were never in info.
- DDM discounts at the cost of equity.
- `vet` shows "DCF: FCF growth X% fading to 2.5% over 10y, discounted at W%; the price implies Y% starting growth".
- Tests are in `tests/test_valuation.py`.
- Known limits:
  - The latest FCF is the base, so cyclicals at a capex peak (EQNR) still look expensive. Options: normalize the base FCF (average over the cycle) or use analyst growth estimates (yfinance `growth_estimates`) as the starting growth.
  - DDM is shown even for low-payout firms, where it means little.
  - The risk section's beta (2.22 for EQNR.OL) differs from Yahoo's (-0.73); check the alignment in `risk.py`.

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

## Phase 2 as built (notes for later phases)

- `src/vetting/`: `red_flags.py` (one function per rule, `find_red_flags(report)`), `peers.py` (Yahoo industry/sector peers since 2c; `percentile_rank`, `compare_to_peers`), `ownership.py` (13F from the discover cache, matched by CUSIP map or issuer name), `verdict.py` (fair value range, signal flip prices by bisection over a repriced report), `vet.py` (`vet_ticker() -> VetResult`), `render.py` (text + Markdown from `VetResult.to_dict()`).
- Scoring: `ValuationScoringParams.peer_relative` / `min_peers`. `StockScorer.score` reads `report["peer_valuation"]`; with 4+ P/E peers the P/E cutoffs are scaled so `pe_fair` = peer median. Only `vet` adds `peer_valuation`, so `report`/`score` are unchanged.
- Pipeline: `report["signals"] = {pead, relative_strength}`. PEAD uses `earnings_dates` (announcement dates), sorted newest first. `fundamental_analysis.analysis.annual_history` has per-year FCF, shares, dividends paid, EBIT, interest, interest cover (feeds red flags; useful for Phase 4 history too). `FundamentalAnalyzer.calculate_all()` is now memoized (Phase 6 item done).
- Info now includes `ev_to_ebitda`, `enterprise_value`, `current_price`, `shares_outstanding`, `free_cashflow`, `financial_currency`. Older cached info.json files lack them until refreshed (info TTL).
- Fixed along the way: 13F values were multiplied by 1000 (SEC reports whole dollars since 2023); `compare` correlation now aligns cross-exchange prices by trading date.
- Known gaps: the DCF growth problem (EQNR: -43%/yr projected for 5 years) was fixed in 2d. FCF yield never scored, because `ValuationScorer` looked for `fcf_metrics` in `valuation_analysis`; fixed 2026-10-22: `StockScorer` passes `fundamental_analysis.analysis.fcf_metrics.fcf_yield` in, banks and insurers skip it, and `verdict.reprice_report` scales that field. On the cached data it moved composites by about a point (AAPL, EQNR.OL and MSFT all score Low, 0.6-1.9%).

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

## Phase 2b: Vet follow-ups

Build on established sources where they exist; keep our own maths only where no free source gives the number.

1. **Verdict summary (done).** `vet` opens with `VERDICT: Look deeper / Watch / Pass`, a one-line list of reasons, and the nearest signal flip within ±50%. `--brief` prints only that, the key facts, and next steps. The rules are in `vetting/vet.py::summarize_verdict`.
2. **Peers from Yahoo's industry lists (done; simplified in 2c, see below).** As built: `DataFetcher.get_industry_peers` / `get_sector_peers` (cached in `data/_peer_groups/`, `industry` TTL). `peer_valuation` tries a cascade (US: Yahoo industry, Yahoo sector, local cache; other listings: same-exchange cache industry peers first). Yahoo peers must be within 10x of the target's USD market cap, because Yahoo's lists mix mega and micro caps (Consumer Electronics gave Apple Sonos and AXIL). Other listings of the same company are dropped, and peers' P/S and EV/EBITDA are FX-corrected. Original notes: yfinance (1.7, already a dependency) has `yf.Industry(info["industryKey"]).top_companies`, which is Yahoo's own industry peer list. Make it the default auto-peer source and keep the cache scan as the fallback and for local-market peers (Yahoo's lists are mostly US large caps, so an Oslo ticker would get US giants). Needs `industryKey` in `get_ticker_info`. Other options (Finnhub `/stock/peers`, FMP) need API keys.
3. **Analyst targets as a fair-value anchor (done).** Shown first in the fair value table, and as a verdict reason with 3+ analysts. Original notes: Yahoo info already carries `targetMeanPrice`, `targetLowPrice`, `targetHighPrice`, `numberOfAnalystOpinions`, and `recommendationMean`. Extract them and show them next to Monte Carlo/DCF, because they're an outside view and don't depend on our DCF.
4. **Fix the DCF/Monte Carlo currency mix (done).** `_RunFetcher.fetch_fundamentals` returns statements converted with `utils/fx.py` (share counts and tax rates are left alone); the cache keeps the original currency; `report["currency_conversion"]` records the rate. Also fixes FCF yield and Altman Z for such tickers. Yahoo's own P/S and EV/EBITDA mix currencies too (EQNR: P/S 8.4 = NOK market cap / USD revenue; really 0.9), so `utils/fx.adjust_info_ratios` corrects the target's report info. Yahoo's `freeCashflow` currency is inconsistent and is never corrected. Original notes: (statements in USD, price in NOK). Convert statement figures with a Yahoo FX pair (`USDNOK=X`) before valuing. Until this is done, `vet` shows a low-severity flag and the fair value numbers are wrong for such tickers.
5. **Keep as is:** peer median/percentile maths (about 20 lines; no free service computes it for your own peer set), relative strength (IBD's RS Rating is proprietary; ours is an index-relative look-alike from prices we already fetch), and PEAD/SUE (not offered free anywhere).

## Phase 2c: Simplify (standard practice over workarounds)

Phase 2b grew workarounds for Yahoo's free-data quirks. Bring it back in line with how this is usually done: normalize data once when it comes in, compute from the normalized data, and keep peer selection to a rule that fits in one sentence.

**Standard practice, and where we stand**

- **Normalize at ingestion, then compute your own ratios.** Convert everything to one currency when the data arrives and calculate multiples yourself instead of trusting a vendor's pre-computed ratios. We convert statements (keep this), but we also patch Yahoo's pre-computed ratios, for the target and for peers. Patching vendor ratios is the part to shrink.
- **Peers: classification + size filter + analyst override.** Professionals use an industry classification (GICS/ICB) plus a size band, or a vendor's peer list, and let the analyst edit it. Our cascade (4 sources, same-exchange rule, universes, size band) is more than this needs.
- **Medians, percentiles, minimum peer count.** Already done; keep.
- **Industry benchmark medians** (Aswath Damodaran, NYU Stern: free yearly industry multiples by region, e.g. US, Europe, global) are a standard outside reference for relative valuation that needs no peer fetching.
- **Cleaner data vendors** (Financial Modeling Prep, Finnhub, EODHD) have normalized fundamentals and peer endpoints, but their free tiers cover Oslo poorly. Yahoo stays the data source.

**Tasks**

1. **One peer rule:** `--peers` if given; otherwise Yahoo's industry list, falling back to Yahoo's sector list, filtered to similar size (0.1x-10x USD market cap) with other listings of the same company dropped. Remove the local-cache peer scan (`find_auto_peers`, `load_cached_infos`, `cached_universes`, same-exchange ranking) and the per-listing ordering. Oslo-only comparisons use `--peers`, e.g. `quant vet EQNR.OL --peers AKRBP.OL,VAR.OL`. Update `next_steps` and the chat context builder, which currently use cache-only peers (chat could use the peers saved in `vet.json`, or skip peers when there is none).
2. **No FX correction for peers:** a peer whose statements are in another currency gets its P/S, EV/EBITDA and FCF yield skipped (these are rare in Yahoo's mostly-US lists). Remove `_correct_currency` and the `fx_lookup` correction path; keep `fx_lookup` only for the size filter.
3. **Keep:** statement conversion in the pipeline, `adjust_info_ratios` for the target (it's the "normalize once" step for the ratios we show), the size filter, medians/percentiles, and `min_peers`.
4. **Consider computing the target's multiples from converted statements** (P/S from revenue, EV/EBITDA from EBITDA and net debt) instead of correcting Yahoo's. Do this only if it doesn't add a second code path; peers still use Yahoo's ratios, so both sides should use the same definitions (TTM).
5. **Optional: Damodaran industry medians** as a "vs industry" column (map Yahoo industries to Damodaran's; cache the yearly file under `data/_benchmarks/`). Only if the peer table proves too noisy.
6. Update tests (drop the local-cache peer tests, keep size/sector/same-company tests), README, and this file.

**As built (2026-09-28)**

- `peers.py` went from 464 to 325 lines. `peer_valuation(ticker, info, fetch_info, peers=None, industry_peers=None, sector_peers=None, fx_lookup=None, min_peers=4)`: explicit peers are used as given (same-company listings dropped, no size filter); otherwise Yahoo's industry list, or its sector list when the industry has fewer than `min_peers` similar-size peers (if both are short, the larger group wins, and ties go to the industry). The basis is `explicit`, `yahoo_industry`, `yahoo_sector` or `none`. `fetch_info` is now required, and there is no `data_dir`.
- Removed: `load_cached_infos`, `cached_universes`, `find_auto_peers`, `_peer_rank`, `_correct_currency`, and the per-listing option order. `fx_lookup` is only used by `_similar_size` (through `usd_per_unit`). A peer whose USD size can't be worked out is dropped by the size filter.
- `metric_value` still skips statement-based ratios (P/S, EV/EBITDA, FCF yield) when statements and price use different currencies and the ratio wasn't corrected. After this change only the target is ever corrected (`adjust_info_ratios` in the pipeline).
- Task 4 (compute the target's multiples from statements) was not done. Peers use Yahoo's TTM ratios, so computing the target's from annual statements would make the two sides inconsistent. `adjust_info_ratios` stays as the single normalization step. Task 5 (Damodaran) was skipped as optional.
- `next_steps`: when no peers are found, it suggests `--peers`. For non-US listings with automatic peers, it notes that Yahoo's lists are mostly US and suggests `--peers T1.OL,...`.
- Chat: `_build_context` reads `peer_valuation` from `data/<T>/reports/vet.json` (written by `vet --save`). Without that file there's no peer section, so startup stays offline.

**Follow-ups after the first live run (2026-09-28)**

- **EQNR got refiners and midstream names:** Yahoo's `oil-gas-integrated` list is XOM, CVX, NFG, DEC, SLNG. Only XOM and CVX are within the size band, so it fell back to the Energy sector list, and the 10 names closest in size pushed XOM and CVX out. Now similar-size industry peers are kept first and the sector list only fills up to `MAX_YAHOO_PEERS`. The sector list is only fetched when the industry list is short. The basis is `yahoo_industry_sector` when both lists contributed, and `yahoo_sector` when no industry peer survived the size filter (AAPL).
- **Oslo `--peers` lost EV/EBITDA and P/S, and P/B was wrong:** AKRBP.OL and VAR.OL report in USD. Yahoo's P/B for VAR.OL was 59.7 (NOK price / USD book value per share), while EQNR.OL's was right. This partly reverses 2c task 2: `utils.fx.normalize_info(info, fx_lookup)` now applies to every peer (in `vet_ticker`'s `fetch_info`). It is the same `adjust_info_ratios` the pipeline runs for the target. `adjust_info_ratios` records `converted_ratios`, which replaces `statements_converted_at`, and `metric_value` skips statement-based ratios (now including P/B) that aren't in that list. The target's P/B is recomputed as market cap / converted common equity (latest quarterly balance sheet, then annual; see `pipeline._latest_book_equity`). Peers' P/B can't be converted from info alone, so it's skipped for mixed-currency peers.
- **Old cached info lacked `financial_currency`:** `DataFetcher.INFO_CACHE_VERSION` (currently 2) is stored in info.json, and older files are refetched. Bump it whenever `get_ticker_info` gains fields.
- **`Minimal or no information returned for WTO`** (a delisted name in Yahoo's list) is now logged at info level. Explicit peers with no data still show under "No data for".
- **Other sources considered:** free tiers of FMP, Finnhub and Alpha Vantage cover Oslo poorly. Børsdata's API (Nordic) and EODHD's fundamentals need a paid plan and a key. SEC XBRL is free but US-only. Yahoo stays, and the conversion step above is applied to every ticker.

**Done when:** the peer rule in the README is one sentence, `src/vetting/peers.py` is noticeably shorter, all tests pass, and `quant vet EQNR.OL` / `quant vet AAPL` render sensible live peer groups (AAPL: Yahoo sector large caps such as MSFT, NVDA, AVGO; EQNR: similar-size integrated oil/energy names).

## Phase 3: Review a portfolio

Input: the holdings you own. Output: per holding, **Exit / Trim / Hold / Add**, plus portfolio-level problems. Runs `vet` on every holding, so it builds directly on Phase 2.

1. **Input file (done, see "Current state" above):** `portfolio/portfolio.csv` (gitignored), built from Nordnet holdings exports by `quant import-portfolio`. Columns: `ticker, name, account, shares, cost_basis, currency`. `review` reads this file; it doesn't need to parse Nordnet files itself.
2. **Per holding:** the vet verdict and red flags, current weight vs a risk-parity weight, unrealized gain/loss if a cost basis is given, and distance to the signal flip prices.
3. **Action rules (explicit and testable, like the red flags):**
   - Exit: `Pass` verdict (a high red flag or a Sell signal).
   - Trim: weight well above risk-parity/target weight, or highly correlated with a larger holding (redundant).
   - Add: `Look deeper` verdict, below target weight, and not redundant.
   - Hold: everything else.
   - Each action comes with one-line reasons, the same way the verdict summary does.
4. **Portfolio level:** sector/industry and currency concentration, correlated clusters (from `identify_correlation_flags`), weighted score and beta, and suggested weights.
5. **CLI:** `quant review [portfolio/portfolio.csv] [--config] [--json] [--save]`. `--save` writes under the gitignored `portfolio/`, not `data/`. The output leads with a summary table (ticker, weight, verdict, action, one reason); details follow.
6. **Caveats in the output:** these are rule-based suggestions, not advice. Taxes are ignored (e.g. selling outside an ASK realizes gains), and the valuation limits from Phase 2b still apply.

**Done when:** a synthetic portfolio in tests gets the expected action per holding for each rule, and `quant review` on the user's real file renders from live data. The README is updated.

**As built (2026-10-22)**

- `src/portfolio/review.py`:
  - `load_portfolio(path)` aggregates the rows by ticker across accounts. Shares are summed, cost basis is share-weighted, and the account labels are kept. Rows with no ticker are reported as unmapped.
  - `review_portfolio(holdings, fetcher, options, base_currency="NOK", workers)` runs `vet_ticker` per holding (concurrently) and values each holding in the base currency with `utils.fx.conversion_rate`, which also handles GBp-style minor units.
  - Gain is computed in the cost currency.
  - Targets are inverse-volatility weights from `calculate_risk_parity_weights`, computed from local-currency prices, so FX volatility is ignored.
  - The overlap check uses `return_correlations(prices, pairwise=True)`, a new function in `comparison/comparator.py` that the comparator now calls too. In pairwise mode a short history or a foreign holiday calendar doesn't shrink every pair (60 shared days minimum).
- `decide_action(review)` is a pure function holding all the rules. The thresholds are module constants:
  - `OVERWEIGHT_RATIO` 1.5 and `OVERWEIGHT_MIN_GAP` 2 points.
  - `REDUNDANT_CORRELATION` 0.80, compared against a *larger* holding only, so only the smaller of a pair is trimmed.
  - `SECTOR_LIMIT` 35%.
  - Order: Check (no price or no score) > Exit (Pass) > Trim (overweight or overlap) > Add (Look deeper, below target) > Hold.
  - Reasons omit the verdict itself, since it has its own column. An Exit leads with its red flag when there is one.
- **Funds:** `info["quote_type"]` was added (`INFO_CACHE_VERSION` 3), with the name as a fallback ("ETF"/"UCITS"). A fund is never Exit or Add, and its "Fund" sector isn't flagged as concentration.
- **Tax note:** when an Exit or Trim would sell at a gain, the reasons say "sell from the ASK first" if the holding is in ASK and another account, or "selling realizes X% gain in AF". This only works once the accounts are labelled.
- `src/portfolio/render.py` reuses the vet layout through the new `vetting.render.sections_to_text/markdown`. Sections: summary table, portfolio (beta, diversification, sector/currency mix, correlated pairs), details for non-Hold holdings, notes/caveats.
- `identify_correlation_flags` now skips NaN pairs instead of failing.
- **Known limits:**
  - Every holding is vetted with peers, so the first run makes many Yahoo calls. Add a `--no-peers` option if that's too slow.
  - The risk-parity target treats every holding alike. A broad ETF probably deserves a larger target than a single stock (possible option: a per-ticker target column in the portfolio file).

## Phase 4: Track

1. **Watchlist.** `watchlist.toml` in the repo root (gitignored, since it's personal). Each entry has a ticker, an optional one-line thesis, the date added, and an optional target/stop.
   - `quant watchlist add T --thesis "..."`, `quant watchlist rm T`, `quant watchlist ls`.
   - Add `quant screen ... --add-to-watchlist N` to add the top N results.
   - `watchlist` should also work as a universe name in `screen`.
2. **Score history.** Every `report`/`score`/`vet`/`screen` stage-2 run appends a row to `data/_history/scores.csv`: date, ticker, preset, composite, the four dimension scores, signal, price, and red-flag count. Deduplicate to one row per ticker, preset, and day.
3. **`quant changes`.** For the watchlist (or given tickers), refresh and show changes since the last history row: score delta, signal changes, new or resolved red flags, price vs target/stop, and upcoming earnings within 14 days. This replaces the polling loop in `watch`. Keep `watch` for intraday use, but point to `changes` for daily use.
4. **Chat context.** Include the ticker's score history (last N rows) so `quant chat` can answer "why did the score drop?"

**Done when:** add, change, and remove work with offline tests. After two runs on different days (simulate by editing history in a test), `changes` reports the deltas. The README is updated.

**As built (2026-10-22)**

- `src/tracking/`:
  - `watchlist.py`: `load_watchlist` / `save_watchlist` / `add_to_watchlist` / `remove_from_watchlist`. `watchlist.toml` (gitignored, `DEFAULT_WATCHLIST`) has one quoted table per ticker (`["EQNR.OL"]`) with `thesis`, `added` (a TOML date), `target` and `stop`. It's read with `tomllib`; the writer is a few lines, since the layout is fixed (strings are written as JSON strings, which are valid TOML). Re-adding a ticker updates only the fields given and keeps `added`.
  - `history.py`: `history_row(report, scoring, source, red_flags, today)`, `record_scores(rows, data_dir)`, `load_history(data_dir, ticker, preset)`. The file is `data/_history/scores.csv`, written atomically, with columns date, ticker, preset, source, score, the four dimensions, signal, confidence, price, currency, red_flags (count) and flags (titles joined by " | ", so `changes` can tell new from cleared). One row per (date, ticker, preset); the later run wins. No row is written without a score and a price: an unknown symbol still gets a meaningless score.
  - `changes.py`: `track_changes()` runs `analyze_ticker` (no peers, no context) and `find_red_flags` per ticker, compares with the latest row for the same preset from an earlier day, then records today's rows. `TickerChange.notes()` holds the rules: a signal change, a score move of `SCORE_MOVE` (3) or more, dimensions that moved `DIMENSION_MOVE` (5) or more, new or cleared red flags, price within `NEAR_LEVEL_PCT` (5%) of or past the target/stop, and earnings within `EARNINGS_SOON_DAYS` (14). The price change is shown only when the currency is the same. `render_text` reuses `vetting.render` sections.
- **Comparable history:** `vet` rescales P/E against peers, so `VetResult.base_scoring` keeps the score from before the peer rescore, and that is what `vet` records. Every row in the history is on the standard valuation cutoffs.
- **Recorded by** `report`, `score`, `vet`, `screen` (stage 2: `ScreenCandidate.report` keeps the report) and `changes`. `review` doesn't record yet; it would need `base_scoring` passed through `review_portfolio`.
- **CLI:** `quant watchlist [--file] add/rm/ls` (ls shows each ticker's last history row), `quant changes [TICKERS] [--config] [--file] [--json]`, `quant screen ... --add-to-watchlist N` (the thesis notes the screen; tickers already listed keep their thesis), and `watchlist` as a screen universe. `watch` points to `changes` for daily use. stderr is now UTF-8 too, so the progress marks (✓/✗) print on Windows.
- **Chat:** `build_brief_context(..., score_history=rows)` adds the last `CHAT_HISTORY_ROWS` (12) rows.
- **Tests:** `tests/test_tracking.py`. `tests/test_cli.py` now runs in a temp working directory, because commands write the history under `./data`.
- **Live check for the user:**
  ```
  quant watchlist add EQNR.OL --thesis "..." --target 450 --stop 380
  quant watchlist add AAPL MSFT
  quant changes          # day 1: baseline
  quant changes          # next trading day: deltas
  quant watchlist ls
  quant screen sp100 --top 10 --add-to-watchlist 3 --no-save
  quant chat EQNR.OL --debug-context   # should show SCORE HISTORY
  ```

## Phase 5: Trust (backtest & calibration)

Price-only walk-forward test of the signals that can be computed point-in-time.

1. `src/backtest/`: for each month-end in the last N years and each ticker in a universe, compute the technical score, risk score, and factor-ranker momentum/low-vol using only data up to that date. Record the forward 1/3/6-month returns, both raw and relative to the benchmark.
2. Report: rank IC (Spearman) per signal and horizon, quintile spread (top minus bottom), and hit rate, with confidence intervals.
3. **Be explicit about the limit:** Yahoo's statements are not point-in-time (restated, and published with a lag), so the fundamental and valuation dimensions can't be backtested honestly this way. Label this in the output and the README.
4. **Calibrate.** Only a score of 50-65 counts as "Hold"; 49 is labelled "Sell" (`SignalThresholds` in `src/scoring/config.py`). Use the backtest to set the thresholds and preset weights, or to document that they are heuristics.
5. `quant backtest sp100 --years 5` prints the table and saves it to `data/_backtests/`.

**Done when:** the backtest runs offline on synthetic prices in tests, and live on sp100. The signal thresholds are either justified by results or documented as heuristics.

**As built (2026-10-22, tasks 1-3 and 5; task 4 waits for the live run)**

- `src/backtest/engine.py`: `run_backtest(tickers, fetcher, years, horizons, config, ...)`. Prices are fetched once per ticker with the shortest Yahoo period covering the test plus a lookback year (`history_period`: 2y, 5y, 10y or max), and each home benchmark (`benchmark_for`) once. For each of the last `years*12` complete months (`backtest_months`), the last bar of the month (`month_end_positions`, which uses `trading_dates` because cached prices come back in UTC) ends a `LOOKBACK_BARS` (252) window. `score_window` runs `TechnicalAnalyzer` and `RiskMetrics.calculate_scoring_metrics` (new: only the six metrics `RiskScorer` reads, a tenth of the cost of `calculate_all_metrics`, which now builds on it). It then calls the real `StockScorer` on a report with only those two sections, so the composite and signal use the preset's weights and `SignalThresholds`. Momentum and low volatility come from `momentum_12_1` / `inverse_volatility`, now module functions in `discovery/factor_ranking.py` that the ranker also uses. Forward returns run month-end to month-end, raw (`ret_Hm`) and minus the benchmark (`excess_Hm`), only up to the last complete month.
- `src/backtest/stats.py`: per-month cross-sections first (at least `MIN_CROSS_SECTION`, 10 tickers), then the mean over months with Newey-West errors (h-1 lags). Rank IC (Spearman), top-minus-bottom quintile spread, hit rate (months the top fifth beat the bottom fifth), and `band_table` (per signal band: per-month mean excess return with CI, plus the share of ticker-months beating the benchmark, with an "All" baseline row). `summarize` computes everything for excess and raw returns; the text shows excess.
- `src/backtest/render.py`: text/Markdown through `vetting.render`, with the caveats always printed (no fundamentals/valuation, survivorship, close-to-close with no costs, overlapping windows). `save_backtest` writes `data/_backtests/backtest_<universe>_<N>y_<stamp>.json/.md` and `_observations.csv`.
- CLI: `quant backtest UNIVERSE... [--years 5] [--horizons 1,3,6] [--config] [--workers] [--json] [--save/--no-save]`. The universe resolves as in `screen`.
- Speed: about 54 ms per ticker-month, about 80% of it `TechnicalAnalyzer` (spread over finta indicators, ADX the largest). Threads don't help (CPU-bound), so sp100 x 5 years is about 5 minutes after the download. If that's too slow for sp500, use a process pool for the scoring.
- Tests: `tests/test_backtest.py`: UTC month-ends, exact forward and excess returns, no look-ahead (crashing later prices leaves earlier signals unchanged), statistics against hand-computed answers, an end-to-end fake-market run, and the CLI.
- **Live run for the user:**
  ```
  quant backtest sp100
  quant backtest obx --years 5
  quant backtest sp100 --config growth --no-save
  ```
- **Task 4 next:** from the band table, check whether returns rise from Strong Sell to Strong Buy and whether Sell vs Hold vs Buy differ outside their intervals. If they do, keep or move the thresholds; if not, say in the README and `SignalThresholds` that the bands are heuristics. Momentum/low-vol ICs say whether the screen's factor weights hold up.

## Phase 6: Cleanup (do alongside the other phases)

- Split `src/reporting/generator.py` (~900 lines of Markdown formatting) into `reporting/markdown.py`.
- Turn `src/cli.py` into a package (`cli/__init__.py` plus one module per command group). Move table rendering out of the command functions.
- **27 tests skip** because they need `data/AAPL/reports/*.json` (gitignored). Generate a fixture report with the `fake_market` pipeline into `tests/fixtures/` and point `test_scorer.py`/`test_toon_serializer.py` at it.
- `FundamentalAnalyzer.calculate_all()` runs 3 times per report (JSON section, markdown, per-analysis JSON). Memoize it like `ValuationAnalyzer.analyze()`.
- Filters for market cap and volume mix currencies across exchanges (NOK vs USD). Convert with FX rates (`EURUSD=X`-style Yahoo symbols) if it matters.
- Make mypy blocking in CI once the backlog is cleared (currently `continue-on-error`).
- Typing: the user switched Pylance to `standard` (2026-09-28) and wants lint issues fixed in whatever file is being edited. `pandas-stubs`/`types-requests` are in the dev extras (install with `pip install -e .[dev]`), and mypy skips untyped libraries (yfinance, finta, toon, seaborn, matplotlib). Earlier note: the user ran Pylance in `strict` mode. The pandas/yfinance-heavy modules show many "partially unknown" warnings. Options: `pip install pandas-stubs types-requests`, and/or a `[tool.pyright]` section in pyproject that keeps strict for `src/vetting` (already clean under `mypy --strict`) and standard elsewhere.
- `examples/` duplicates the CLI. Keep only what documents the Python API.

## Starting a new session

Paste something like:

> Read docs/ROADMAP.md, starting with "Current state and next session". Go through my live `quant backtest` results (Phase 5) and do task 4: calibrate or document the signal thresholds. Follow its conventions: offline tests with the fake_market fixture and synthetic data; give me live commands to run, since your shell can't reach Yahoo; never commit real holdings or the watchlist.
