# Quantitative Analysis Tool

A Python-based quantitative financial analysis tool for fetching market data, performing technical and fundamental analysis, and generating comprehensive stock reports.

## Features

### Data Fetching

- Historical price data via Yahoo Finance (yfinance)
- Company fundamentals and financial statements
- Earnings data and institutional holdings
- Dividend history and analyst ratings
- Recent news articles
- Caching with per-resource expiry (prices 12h, company info 24h, statements 7d, ...)
- Falls back to the last cached copy when Yahoo is unreachable or rate-limiting, and says so
- Reports flag stale data (e.g. last price bar is 9 days old)

### Technical Analysis

- **Trend Indicators:** SMA, EMA, MACD
- **Momentum Indicators:** RSI, Stochastic Oscillator, Williams %R
- **Volatility Indicators:** Bollinger Bands, ATR, ADX
- **Volume Indicators:** OBV, VWAP, MFI
- Automated signal generation (buy/sell signals)

### Fundamental Analysis

- **Growth Metrics:** Revenue, Earnings, FCF growth (1Y, 3Y, 5Y CAGR)
- **Free Cash Flow Analysis:** FCF yield, FCF margin, FCF per share
- **Profitability Margins:** Gross, EBITDA, Operating, Net margins with trends
- **Efficiency Ratios:** Asset turnover, inventory turnover, cash conversion cycle
- **DuPont Analysis:** ROE decomposition (Margin x Turnover x Leverage)
- **Quality Scores:** Altman Z-Score (bankruptcy risk), Piotroski F-Score (fundamental strength)

### Valuation Analysis

- **DCF Valuation:** two-stage DCF. FCF growth starts at the clamped 3-year history (-10% to +20%) and fades linearly to 2.5% over 10 years. Cash flows are discounted at a CAPM WACC (config risk-free rate, 5% equity risk premium, Blume-adjusted beta, after-tax debt weight), and net debt comes from the balance sheet. A reverse DCF gives the starting growth the current price implies. Monte Carlo runs the same model with varied inputs.
- **DDM Valuation:** Dividend Discount Model (Gordon Growth Model)
- **Dividend Analysis:** Yield, growth rate, payout ratio, coverage, sustainability scoring
- **Earnings Analysis:** EPS trends, surprises, quality assessment (cash flow backing)
- **Multi-Currency Support:** Automatic currency detection and formatting (USD, CAD, NOK, EUR, GBP)

### Risk Analysis

- **Volatility Metrics:** Historical volatility, downside deviation
- **Risk-Adjusted Returns:** Sharpe ratio, Sortino ratio, Calmar ratio
- **Drawdown Analysis:** Maximum drawdown, current drawdown
- **Value at Risk (VaR):** 95% and 99% confidence levels (parametric and historical)
- **Market Risk:** Beta and alpha against the stock's home market (OSEBX for `.OL`, FTSE 100 for `.L`, DAX for `.DE`, ...; S&P 500 for US listings)

### Screening

- **Two-stage screen** over an index or ticker list: a cheap multi-factor ranking of every ticker, then the full composite score for the top N
- **Built-in universes:** S&P 500, S&P 100, Nasdaq-100, OBX (Nasdaq-100 from Nasdaq's official constituent list, others from Wikipedia; cached for 30 days), plus the latest `discover` consensus picks
- **Factors:** Value (earnings yield, book/price), Quality (ROE, leverage), Momentum (12-minus-1 month), Low Volatility; each ranked cross-sectionally
- **Filters:** sector/industry include/exclude, market cap range, minimum volume
- Results saved as CSV (spreadsheet-friendly), JSON, and TOON

### Vetting

- **One-screen verdict** on a single ticker (`quant vet`), without writing report files
- **Red flags:** Beneish M-Score, Altman Z distress, repeated negative FCF, share dilution, uncovered dividend, weak interest cover, stale statements, low data coverage, stale data, statements in a different currency than the price
- **Peer-relative valuation:** P/E, forward P/E, EV/EBITDA, P/S, P/B and FCF yield against the peer median, with percentile rank. With 4+ peers, the P/E sub-score is judged against the peer median instead of fixed cutoffs
- **Signals:** post-earnings drift (SUE) and relative strength against the home-market benchmark
- **13F fund activity** from the `quant discover` cache: which tracked funds hold it and whether they bought, added, trimmed or exited
- **What would change the verdict:** analyst price targets, Monte Carlo/DCF/DDM fair value range, the price at which the signal moves one band up or down, and trade levels
- **Currency-safe valuation:** when a company reports in another currency than it trades in (EQNR.OL: USD vs NOK), statements are converted at the latest Yahoo FX rate before any analysis

### Tracking

- **Watchlist** in ``watchlist.toml`` (gitignored): ticker, a one-line thesis, the date added, and an optional target and stop price. Add by hand, with ``quant watchlist add``, or straight from a screen with ``--add-to-watchlist N``
- **Score history:** every ``report``, ``score``, ``vet``, ``screen`` (stage 2) and ``changes`` run adds one row per ticker to ``data/_history/scores.csv`` (one row per ticker, preset and day)
- **What changed:** ``quant changes`` rescores the watchlist and compares it with the last run from an earlier day: score and signal, red flags that appeared or cleared, price move, price against target/stop, and earnings in the next 14 days
- ``quant chat`` sees the ticker's score history, so you can ask why a score dropped

### Portfolio Discovery

- **Cross-portfolio pattern detection** from SEC EDGAR 13F filings (free, no API key)
- **Quarter-over-quarter diff:** Compares 2 consecutive filings to infer new/exit/add/trim/hold actions
- **Ticker Overlap:** Find consensus picks held by multiple institutional investors
- **Sector/Industry Clustering:** Granular concentration patterns (not just "Technology" but "Semiconductors", "Internet Retail", etc.)
- **Activity Convergence:** Detect multiple portfolios buying/selling the same ticker within a time window
- **Contrarian Signals:** Spot disagreement — some whales buying while others sell
- **Auto-enrichment:** Top overlap tickers automatically enriched with sector/industry from yfinance
- Pre-configured notable filers: Berkshire Hathaway, ARK, Soros, Bridgewater, Renaissance, Pershing Square, Appaloosa, Icahn
- Pluggable source architecture for adding paid data sources later
- TOON output for LLM-based reasoning about discovery signals

### Composite Scoring

- 0-100 score across four dimensions: Technical, Fundamental, Risk, Valuation
- Valuation weighs DCF, P/E, PEG, FCF yield, dividend sustainability and earnings quality. Banks and insurers skip the cash-flow measures (DCF, FCF yield)
- Configurable presets: ``default``, ``value``, ``growth``, ``income``
- Scorecard output with strengths and concerns
- Buy/Hold/Sell bands: Strong Buy 80+, Buy 65-80, Hold 50-65, Sell 35-50, Strong Sell below 35. ``quant backtest`` shows how the price-based part of these has done

### Backtest

- **Walk-forward test** of the signals that can be computed from prices alone: the technical and risk scores, their composite (with the real Buy/Hold/Sell bands), 12-1 momentum and low volatility
- At each month-end, only prices up to that day are used. Forward returns over 1, 3 and 6 months are measured against each ticker's home benchmark
- **Rank IC, quintile spread, hit rate** and **returns per signal band**, with 95% intervals (Newey-West, for the overlapping windows)
- Fundamental and valuation scores are not tested: Yahoo's statements are restated and undated, so they can't be used as of a past date

### Report Generation

- JSON reports with complete data aggregation
- Markdown reports for human-readable analysis
- TOON reports for LLM-optimized input (Token-Oriented Object Notation)

### Interactive Analyst Chat

- Conversational Q&A session grounded in the full quantitative report
- Supports Anthropic (Claude) and OpenAI / GitHub Models (free tier)
- Auto-generates the report on first use — no need to run ``report`` first
- Maintains full conversation history across turns for follow-up questions
- Opening investment brief generated automatically on session start
- In-session ``/refresh`` command to re-fetch live data mid-conversation

## Installation

Requires Python 3.14+. All dependencies are declared in `pyproject.toml`.

```powershell
py install 3.14                  # Python install manager (Windows)
py -V:3.14 -m venv venv
.\venv\Scripts\Activate.ps1      # macOS/Linux: source venv/bin/activate
python -m pip install -U pip
pip install -e ".[all]"
```

Optional extras (combine as needed, e.g. `".[llm,dev]"`):

- `llm` -- anthropic, openai (required for `quant chat`)
- `viz` -- matplotlib, seaborn (correlation heatmap in `quant compare`)
- `all` -- `llm` + `viz`
- `dev` -- pytest, ruff, mypy

## CLI Reference

### ``quant report`` -- Single-ticker deep dive

Generates a full report with scorecard for one ticker. Prints dimension scores, strengths, and concerns. Saves JSON, Markdown, and TOON files.

```bash
quant report AAPL
quant report EQNR --period 2y
quant report MSFT --exclude-technical --no-cache
quant report AAPL --format toon
quant report EQNR.OL --config income
```

Options:
- ``--exclude-technical / --exclude-fundamental / --exclude-risk / --exclude-valuation``
- ``--config [default|value|growth|income]`` -- scoring weight preset (recorded in the saved scoring files)

### ``quant score`` -- Multi-ticker screening table

Scores one or more tickers and prints a compact summary table. Use this for screening and ranking a watchlist.

```bash
quant score AAPL MSFT TSLA
quant score NVDA AMD --config growth
quant score EQNR BP --config value
```

Options:
- ``--config [default|value|growth|income]`` -- scoring weight preset
- ``--workers N`` -- tickers analyzed in parallel (default 4)

### ``quant screen`` -- Find candidates across an index

Ranks every ticker in a universe with a multi-factor model, then runs the full analysis and composite score on the best ``--top`` candidates.

```bash
quant screen sp500 --top 25 --config value
quant screen obx --exclude-sector Energy
quant screen nasdaq100 --sector Technology --min-mcap 50B
quant screen discover                         # score the whales' consensus picks
quant screen my_tickers.txt EQNR.OL DNB.OL    # ticker file + literal tickers
quant screen watchlist                        # the tickers in watchlist.toml
quant screen sp100 --add-to-watchlist 5       # put the 5 best on the watchlist
quant screen --list                           # show built-in universes
```

UNIVERSE can be any mix of:
- a built-in index: ``sp500``, ``sp100``, ``nasdaq100``, ``obx``
- ``discover``: overlap tickers from the last ``quant discover`` run
- ``watchlist``: the tickers in ``watchlist.toml``
- a ticker file: one or more per line (comma/space separated, ``#`` comments) or a CSV with a ``ticker``/``symbol`` column
- literal tickers

**How it works:**

1. **Rank (whole universe):** fetches company info and one year of prices per ticker, applies filters, and ranks each ticker against the others on Value, Quality, Momentum, and Low Volatility (percentiles, 100 = best).
2. **Score (top N):** runs the full technical/fundamental/risk/valuation analysis on the ``--top`` factor-ranked tickers. Stage-1 data is reused from the cache.

The table lists the scored candidates by composite score with their factor rank and factor percentiles. Results are saved to ``data/_screens/`` (a timestamped file plus ``latest.csv``/``latest.json``).

Options:
- ``--top N`` -- candidates to fully score (default 20)
- ``--config [default|value|growth|income]`` -- scoring preset
- ``--sector TEXT`` / ``--exclude-sector TEXT`` -- sector or industry substring, repeatable
- ``--min-mcap`` / ``--max-mcap`` -- market cap, e.g. ``500M``, ``10B``, ``1T`` (in the listing's own currency)
- ``--min-volume`` -- average daily volume in shares, e.g. ``500K``
- ``--workers N`` -- parallel downloads (default 4; Yahoo rate-limits aggressive clients)
- ``--no-save`` -- print only
- ``--add-to-watchlist N`` -- add the N best-scoring results to ``watchlist.toml`` (the thesis notes the screen; tickers already listed keep theirs)

**Performance:** the first ``sp500`` screen downloads info and prices for about 500 tickers, which takes a few minutes. Later runs within the cache TTL take seconds.

### ``quant vet`` -- Should this ticker get a deeper look?

Prints a one-screen verdict for a single ticker. It opens with ``VERDICT: Look deeper / Watch / Pass`` and the reasons on one line: Pass means a high-severity red flag or a Sell signal, and Look deeper means a Buy signal with at least medium confidence. Then come the details: header (score, signal, confidence, preset), red flags, peer valuation, signals, 13F fund activity, what would change the verdict, strengths/concerns, and next steps. Nothing is written to disk unless you pass ``--save``.

```bash
quant vet EQNR.OL
quant vet AAPL --peers MSFT,GOOGL,META
quant vet EQNR.OL --peers AKRBP.OL,VAR.OL  # home-market peers
quant vet NVDA --config growth --save      # also writes data/NVDA/reports/vet.json + vet.md
quant vet AAPL --json                      # machine-readable
```

Options:
- ``--peers T1,T2,...`` -- explicit peer group, used as given (no size filter)
- ``--config [default|value|growth|income]`` -- scoring preset
- ``--brief`` -- only the verdict, key facts, and next steps
- ``--json`` -- print the result as JSON
- ``--save`` -- write ``vet.json`` and ``vet.md`` to ``data/TICKER/reports/``

**Peers:** your ``--peers``; otherwise Yahoo's industry list, topped up from its sector list when fewer than 4 remain, keeping companies within 0.1x-10x of the ticker's USD market cap and dropping other listings of the same company.

Yahoo's lists (``yf.Industry``/``yf.Sector`` ``top_companies``, cached for 30 days) are mostly US companies, so use ``--peers`` for home-market comparisons. Ratios are Yahoo's own (TTM). Many companies report in one currency and trade in another (most Oslo energy names report in USD), and Yahoo mixes the two in P/S, EV/EBITDA and sometimes P/B. For every ticker, the ticker itself and its peers, P/S and EV/EBITDA are converted at the latest FX rate. P/B is recomputed from the converted balance sheet for the ticker, and is left out for such peers. FCF yield is left out for such tickers.

**Peer-relative scoring:** when at least 4 peers have a P/E, ``vet`` rescores with the P/E cutoffs scaled around the peer median, so its score can differ slightly from ``report``/``score``. Turn it off with ``"peer_relative": false`` under ``valuation`` in a scoring config.

**Statements in another currency** (e.g. USD statements for a NOK-listed share) are converted into the listing currency at the latest Yahoo FX rate (``USDNOK=X``) before any analysis, so DCF, Monte Carlo, FCF yield and Altman Z use one currency. The fair value section says which rate was used. If no rate is available, a red flag says the values mix currencies.

**Signal flip prices** hold everything except price-driven valuation inputs (multiples, DCF premium, FCF yield) constant. They show how far the price must move for valuation alone to change the signal, not a price target.

**13F activity** needs the cache from ``quant discover``. Holdings are matched by ticker (through the CUSIP map) or by issuer name, which also finds US ADRs of foreign listings.

### ``quant compare`` -- Side-by-side comparison

Compares two or more tickers across scores, relative valuation, key metrics, and return correlation. It also flags highly correlated pairs (above 0.8) and hedges (below -0.3), and suggests risk-parity (inverse volatility) weights. Use this for head-to-head evaluation before a buy decision.

```bash
quant compare AAPL MSFT
quant compare AAPL MSFT GOOGL --weights 0.5,0.3,0.2
quant compare EQNR BP --save-chart data/corr.png
```

Options:
- ``--weights`` -- comma-separated portfolio weights for a portfolio summary view
- ``--save-chart`` -- save correlation heatmap to a file (requires matplotlib)
- ``--config [default|value|growth|income]`` -- scoring preset

### ``quant chat`` -- Interactive analyst session

Opens a conversational session for a single ticker. The LLM has the full quantitative report in context for every question — ask about risks, run hypothetical scenarios, or drill into any metric.

**If no report exists yet, ``chat`` generates one automatically before starting the session.** If a report already exists (e.g. from a previous ``report`` run), it is loaded instantly.

```bash
quant chat EQNR
quant chat AAPL --model claude-sonnet-4-5
quant chat MSFT --no-intro          # skip opening brief, go straight to the prompt
quant --no-cache chat TSLA          # force fresh data fetch before starting
```

Options:
- ``--model`` -- LLM model override (e.g. ``gpt-4o``, ``claude-sonnet-4-5``). Reads ``llm_model`` from ``config.json`` if not set.
- ``--no-intro`` -- skip the automatic opening investment brief
- ``--debug-context`` -- print the context sent to the LLM and exit (useful for debugging)

Peer valuation is included when ``quant vet TICKER --save`` has been run, since chat reads the peers from ``vet.json``. The last 12 rows of the ticker's score history (``data/_history/scores.csv``) are included too, so you can ask what changed.

Special commands during the session:

| Command | Effect |
|---------|--------|
| ``/refresh`` | Re-fetch fresh data, rebuild report, and clear conversation history |
| ``/clear`` | Reset conversation history (report context is always preserved) |
| ``/help`` | Show available commands |
| ``/quit`` | Exit the session |

Example questions to ask:
- *"What is the bear case for this stock?"*
- *"How does the DCF change if I assume 3% growth instead of 5%?"*
- *"Is the dividend safe given the current payout ratio and debt level?"*
- *"What would need to change to upgrade this from Hold to Buy?"*

Requires an API key in ``config.json``:
```json
{
    "llm_model": "claude-haiku-3-5",
    "llm_anthropic_api_key": "sk-ant-..."
}
```
Alternatively, use the free GitHub Models tier with ``"llm_github_token": "ghp_..."`` (no billing required — see [GitHub Models](https://github.com/marketplace/models)).

### ``quant discover`` -- Portfolio signal discovery

Analyzes institutional 13F filings for cross-portfolio patterns. Fetches the **two most recent quarterly filings** for each investor and diffs them to infer buy/sell actions, then detects four signal types across all portfolios.

**How it works:**

1. Fetches latest + previous 13F filings from SEC EDGAR (free, no API key)
2. Diffs holdings quarter-over-quarter to infer actions:
   - ``new`` = position didn't exist last quarter
   - ``exit`` = position completely sold
   - ``add`` = shares increased >5%
   - ``trim`` = shares decreased >5%
   - ``hold`` = shares unchanged (within ±5%)
3. Auto-enriches top overlap tickers with sector/industry from yfinance
4. Runs all 4 pattern detectors: overlap, sector clustering, convergence, contrarian

**Optimal usage order (recommended workflow):**

```bash
# 1. First run — fetch fresh data from SEC EDGAR (takes ~30s)
quant --no-cache discover

# 2. High-conviction consensus picks only (strongest signal)
quant discover --min-overlap 3

# 3. Drill into a sector you're interested in
quant discover --sector Technology
quant discover --sector "Financial Services"

# 4. Full enrichment if you want ALL sector clusters (slower, enriches 800+ tickers)
quant discover --enrich

# 5. See what's configured
quant discover --list-sources
```

**Subsequent runs** use cached data (instant). Clear cache periodically or when new filings are expected:

```bash
# Refresh after mid-Feb / mid-May / mid-Aug / mid-Nov (when new 13F filings appear)
quant --no-cache discover
```

**Tips:**
- The first run without ``--no-cache`` returns cached results instantly
- ``--min-overlap 3`` is the sweet spot — tickers held by 3+ of 8 whales is a strong consensus signal
- Sector data appears automatically for top overlap tickers (auto-enriched via yfinance)
- ``--enrich`` enriches ALL holdings (slow) — usually unnecessary since auto-enrich covers the top results
- 13F data is quarterly, filed ~45 days after quarter-end. Data is 1-4 months stale
- Save TOON output for LLM reasoning: ``quant --format toon discover``
- Rank and score the consensus picks: ``quant screen discover``

**Data freshness schedule:**

| Quarter | Filings appear | Best time to ``--no-cache`` |
|---------|----------------|---------------------------|
| Q1 (Jan-Mar) | Mid-May | After May 15 |
| Q2 (Apr-Jun) | Mid-August | After August 14 |
| Q3 (Jul-Sep) | Mid-November | After November 14 |
| Q4 (Oct-Dec) | Mid-February | After February 14 |

Options:
- ``--min-overlap`` -- minimum portfolios a ticker must appear in (default: 2)
- ``--top`` -- number of top signals to display (default: 20)
- ``--sector`` -- filter results to a specific sector
- ``--enrich / --no-enrich`` -- enrich ALL holdings with sector/industry (slow; top overlap tickers are auto-enriched by default)
- ``--list-sources`` -- list configured portfolio sources without fetching

**Configuration** (``config.json``):
```json
{
    "edgar_user_agent": "PersonalResearch you@email.com"
}
```
SEC EDGAR requires a User-Agent with contact info. No API key needed — all data is free public records.

### ``quant watch`` -- Continuous refresh

Re-scores tickers on a timer with fresh data. Useful for monitoring during market hours. Nothing is written to disk. For a daily check of what moved, use ``quant changes``.

```bash
quant watch AAPL MSFT --interval 60
quant watch EQNR --interval 300 --count 5
```

Options:
- ``--interval`` -- refresh interval in seconds (default: 300)
- ``--count`` -- number of iterations before exiting (default: 0 = infinite)

### ``quant import-portfolio`` -- Nordnet holdings to a portfolio file

Combines Nordnet holdings exports (``Beholdningstabell eksport, kontono. <account>, <date>.csv``, or the older ``aksjelister_konto-<account>_<date>.csv``; one per account) into ``portfolio/portfolio.csv`` with the columns ``ticker,name,account,shares,cost_basis,currency``. Nordnet's export has names but no tickers, so ``portfolio/tickers.csv`` (``name,ticker``) maps names to Yahoo tickers. Unmapped names are listed so you can add them and rerun. ``portfolio/`` and the export file names are gitignored: holdings never go into git.

```bash
quant import-portfolio "~/Downloads/Beholdningstabell eksport*.csv" --label 12345678=ASK --label 87654321=AF   # quote: the names have spaces
quant import-portfolio "~/Downloads/Beholdningstabell eksport*.csv" --verify   # show Yahoo's name/currency per ticker
```

Nordnet's API is closed to retail customers (paid partner access only), so the export is the supported input: in Nordnet's web app, download the holdings list for each account, then run ``import-portfolio`` on the files. Repeat whenever your holdings change.

### ``quant review`` -- Exit / Review / Trim / Hold / Add for each holding

Runs ``vet`` on every holding in ``portfolio/portfolio.csv``, values the holdings in one currency (NOK by default, using Yahoo FX rates), and compares each weight with a risk-parity (inverse-volatility) target. The output starts with one row per holding: action, weight, target, gain, score, verdict and the main reason. The portfolio view follows (beta, sector and currency mix, holdings that move together), then details for every holding that isn't a Hold.

```bash
quant review                           # portfolio/portfolio.csv
quant review --config value --save     # also writes portfolio/review.json + review.md (gitignored)
quant review --json
```

| Action | Rule |
|--------|------|
| Exit | A Sell or Strong Sell signal |
| Review | A high-severity red flag (e.g. Altman Z distress, Beneish M) with a Hold or Buy signal: look into the flag before selling. These models have known false positives, so they don't trigger an Exit for a stock you own; ``vet`` still says Pass for a new candidate |
| Trim | Weight is at least 1.5x its target and at least 2 points above it, or the holding moves with a larger one (daily-return correlation >= 0.80) |
| Add | ``vet`` verdict is Look deeper, the weight is below target, and there's no overlap |
| Hold | Everything else |
| Check | No price data, usually a wrong ticker in ``portfolio/tickers.csv`` |

ETFs and funds have no statements to vet, so they are only ever Trim or Hold. Taxes are ignored, except for a note when a sale at a gain would happen in AF (label your accounts ASK/AF with ``import-portfolio --label``). These are rule-based suggestions, not advice. The first run fetches every holding and its peers, which takes a few minutes; later runs use the cache.

### ``quant watchlist`` -- Tickers you follow

```bash
quant watchlist add EQNR.OL --thesis "Cheap vs peers if oil holds" --target 450 --stop 380
quant watchlist add AAPL MSFT
quant watchlist add EQNR.OL --stop 390        # update one field; the rest is kept
quant watchlist rm MSFT
quant watchlist ls                            # with each ticker's last recorded score
```

The list is ``watchlist.toml`` in the current folder (gitignored, ``--file`` for another), one table per ticker, so it's easy to edit by hand:

```toml
["EQNR.OL"]
thesis = "Cheap vs peers if oil holds"
added = 2026-10-22
target = 450.0
stop = 380.0
```

Target and stop are prices in the listing currency.

### ``quant changes`` -- What moved since the last run

```bash
quant changes                     # the watchlist
quant changes EQNR.OL AAPL        # given tickers
quant changes --config value      # compare value-preset scores
quant changes --json
```

Rescores each ticker, records it in the score history, and compares it with the ticker's latest run from an earlier day (from any command, same preset). Tickers with something worth a look come first:

- signal changes, and score moves of 3+ points (with dimensions that moved 5+)
- red flags that appeared or cleared
- price within 5% of, or past, the watchlist target or stop
- earnings in the next 14 days

The table shows every ticker's score, signal and price change; a ticker seen for the first time gets a baseline. The history (``data/_history/scores.csv``) holds the date, ticker, preset, command, composite and dimension scores, signal, confidence, price, and red flags. Running the same ticker and preset twice in a day keeps the later run. ``vet`` judges P/E against peers, but the history stores its score with the standard cutoffs, so rows from every command compare like with like.

### ``quant backtest`` -- How well did the signals predict?

```bash
quant backtest sp100                      # 5 years, horizons 1, 3 and 6 months
quant backtest obx --years 3 --horizons 1,3
quant backtest sp100 --config growth --no-save
quant backtest watchlist --json
```

At every month-end of the last ``--years`` years, each ticker is scored using only the prices up to that day: the technical and risk dimensions, the composite of the two (the real scorer, with the preset's weights over the dimensions it has), 12-1 momentum and low volatility. The returns over the next ``--horizons`` months are then measured against the ticker's home benchmark (S&P 500, OSEBX, ...).

| Table | What it says |
|-------|--------------|
| Rank IC | Spearman correlation between the signal and the next return, averaged over months. Above about 0.03 is typical for a useful equity signal |
| Quintile spread | Return of the top fifth minus the bottom fifth |
| Hit rate | Share of months the top fifth beat the bottom fifth |
| Signal bands | Mean return vs the benchmark, and the share of stocks beating it, for each Buy/Hold/Sell band of the composite. Useful bands rise from Strong Sell to Strong Buy |

Each statistic is computed across tickers within a month, then averaged over months. Intervals are 95% with Newey-West errors, since monthly samples of 3- and 6-month returns overlap; ``*`` marks an interval that excludes zero (50% for the hit rate).

Limits, also printed with the results:
- Fundamental and valuation scores are not tested. Yahoo serves the latest restated statements with no publication dates, so using them at a past date would leak the future.
- Survivorship bias: the universe is today's constituents.
- Trades at the signal day's close, with no costs. Prices are adjusted, so returns include dividends.

The first run downloads up to 10 years of prices per ticker. Scoring sp100 over 5 years (about 6,000 ticker-months) then takes about 5 minutes. Results go to ``data/_backtests/``: a JSON summary, a Markdown report, and a CSV with every ticker-month's signals and returns for your own analysis.

### Global options

All options below must be placed **before** the subcommand:

```bash
quant --period 2y report AAPL
quant --format json score AAPL MSFT
quant --no-cache compare EQNR BP
quant -v report TSLA
quant -q score AAPL MSFT
quant --output-dir /tmp/data report AAPL
```

| Option | Default | Description |
|--------|---------|-------------|
| ``--period`` | ``1y`` | Data period: ``1mo``, ``3mo``, ``6mo``, ``1y``, ``2y``, ``5y`` |
| ``--format`` | ``all`` | Output format: ``json``, ``markdown``, ``toon``, ``all`` |
| ``--no-cache`` | off | Bypass cache and fetch fresh data |
| ``--output-dir`` | ``data`` | Root directory for cache and reports |
| ``-v / --verbose`` | off | Show debug logging (default shows warnings only) |
| ``-q / --quiet`` | off | Show errors only |

## Configuration

Optional ``config.json`` in the working directory (gitignored). All keys are optional:

```json
{
    "risk_free_rate": 0.04,
    "benchmark_ticker": "^GSPC",
    "benchmark_by_suffix": {".OL": "OBX.OL"},
    "cache_ttl_hours": {"fundamentals": 336, "prices": 6},
    "llm_model": "gpt-4.1",
    "llm_github_token": "ghp_...",
    "edgar_user_agent": "PersonalResearch you@email.com"
}
```

- ``risk_free_rate`` -- annual rate as a decimal (0.04 = 4%), used for Sharpe, Sortino, and alpha
- ``benchmark_ticker`` -- benchmark for US and unmapped listings
- ``benchmark_by_suffix`` -- override the built-in exchange-to-index map in ``src/markets.py``
- ``cache_ttl_hours`` -- max cache age per resource (``prices``, ``info``, ``earnings``, ``analyst_ratings``, ``dividends``, ``fundamentals``, ``holders``, ``universe``, ``industry``). Only keys you set are overridden; ``0`` means never expire.

## When to Use Which Command

| Goal | Command |
|------|---------|
| Find candidates in an index | ``quant screen sp500`` |
| Discover new investment ideas | ``quant discover`` |
| Quick verdict on one stock | ``quant vet TICKER`` |
| What to do with the stocks you own | ``quant review`` |
| Deep dive on one stock | ``quant report TICKER`` |
| Ask follow-up questions / interrogate a stock | ``quant chat TICKER`` |
| Score a few tickers side by side | ``quant score T1 T2 T3 ...`` |
| Compare two candidates | ``quant compare T1 T2`` |
| Keep a list of names to follow | ``quant watchlist add TICKER --thesis "..."`` |
| What moved since last time | ``quant changes`` |
| How much to trust the signals | ``quant backtest sp100`` |
| Monitor during market hours | ``quant watch T1 T2`` |

### Recommended Workflow: Discovery → Analysis

```bash
# Step 1: Find candidates: screen an index, and/or see what the whales are buying
quant screen sp500 --top 25 --config growth
quant --no-cache discover --min-overlap 3     # after new 13F filings appear
quant screen discover --config growth         # rank + score the consensus picks

# Step 2: Score any extra names you're curious about
quant score AAPL NVDA AMZN MSFT BAC --config growth

# Step 3: Vet the best names, then deep dive on the survivor
quant vet NVDA
quant report NVDA

# Step 4: Compare your top 2-3 candidates
quant compare NVDA AMD AVGO

# Step 5: Ask the LLM about risks and thesis
quant chat NVDA
# > "What's the bear case? Is the valuation stretched?"

# Step 6: Follow your picks, and check daily what moved
quant watchlist add NVDA --thesis "AI capex cycle" --stop 150
quant changes
```

## Output Files

Reports are written to ``data/TICKER/reports/``:

```
data/TICKER/
+-- cache/                     # Ephemeral API responses (gitignored)
|   +-- prices_1y_1d.csv
|   +-- info.json
|   +-- fundamentals.json
|   +-- ...
+-- reports/                   # Generated analysis outputs (version-controlled)
    +-- full_report.json
    +-- full_report.toon        # LLM-optimized (TOON format)
    +-- report.md
    +-- scoring.json
    +-- scoring.md
    +-- technical_analysis.json
    +-- technical_analysis.md
    +-- fundamental_analysis.json
    +-- fundamental_analysis.md
    +-- risk_analysis.json
    +-- risk_analysis.md
    +-- valuation_analysis.json
    +-- valuation_analysis.md
```

The score history is ``data/_history/scores.csv`` (see ``quant changes``). Backtests are written to ``data/_backtests/``. Screen results are written to ``data/_screens/`` (``screen_<universe>_<timestamp>.csv/json/toon`` plus ``latest.*``). Index constituent lists are cached in ``data/_universes/``.

Discovery results are written to ``data/_discovery/``:

```
data/_discovery/
+-- edgar_13f/                 # Cached 13F filing data per CIK
|   +-- 0001067983.json        # Berkshire Hathaway
|   +-- 0001697748.json        # ARK Investment
|   +-- ...
+-- enrichment/                # Ticker/sector resolution caches
|   +-- cusip_map.json
|   +-- sector_map.json
+-- discovery_result.json       # Latest analysis output
+-- discovery_result.toon       # LLM-optimized discovery output
```

### TOON Format

Reports are generated in [TOON (Token-Oriented Object Notation)](https://github.com/toon-format/spec) format alongside JSON and Markdown. TOON uses YAML-style indentation for objects and CSV-like tabular rows for uniform arrays, reducing token count while maintaining LLM readability.

TOON is generated by default (``--format all``). Use ``--format toon`` for TOON-only output.

**Note:** The ``news`` section is excluded from TOON output -- its deeply nested structure produces larger output than compact JSON. The full news data remains in the JSON report.

## Project Structure

```
quant-analysis/
+-- src/
|   +-- cli.py                       # CLI entry point (Click subcommands)
|   +-- data_fetcher.py              # Yahoo Finance data fetching with caching + expiry
|   +-- pipeline.py                  # Fetch -> analyze -> score for one ticker (no file I/O)
|   +-- markets.py                   # Exchange suffix -> benchmark index mapping
|   +-- config.py                    # Configuration settings
|   +-- llm.py                       # LLM integration (chat, provider routing, context building)
|   +-- analysis/
|   |   +-- technical.py             # Technical indicators (finta)
|   |   +-- fundamental.py           # Fundamental metrics
|   |   +-- valuation.py             # DCF/DDM valuation & earnings analysis
|   |   +-- risk.py                  # Risk metrics & VaR
|   +-- comparison/
|   |   +-- comparator.py            # TickerComparator & PortfolioView
|   |   +-- formatters.py            # Table, Markdown, JSON, heatmap output
|   +-- discovery/
|   |   +-- models.py                # Data models (Holding, TrackedPortfolio, signals)
|   |   +-- analyzer.py              # Cross-portfolio pattern detection
|   |   +-- enrichment.py            # CUSIP→ticker + sector/industry enrichment
|   |   +-- factor_ranking.py        # Multi-factor cross-sectional ranking
|   |   +-- sources/
|   |       +-- base.py              # PortfolioSource ABC (pluggable)
|   |       +-- edgar_13f.py         # SEC EDGAR 13F source (free)
|   +-- portfolio/
|   |   +-- nordnet.py               # Nordnet holdings export -> portfolio.csv
|   |   +-- review.py                # review_portfolio(): Exit / Trim / Hold / Add rules
|   |   +-- render.py                # Terminal + Markdown output for review
|   +-- reporting/
|   |   +-- generator.py             # Report file writing (runs the pipeline)
|   |   +-- sections.py              # Modular section handlers
|   +-- screening/
|   |   +-- universe.py              # Index lists, ticker files, discover picks
|   |   +-- screener.py              # Two-stage factor rank -> full score
|   +-- backtest/
|   |   +-- engine.py                # run_backtest(): point-in-time signals + forward returns
|   |   +-- stats.py                 # Rank IC, quintile spread, hit rate, bands (Newey-West)
|   |   +-- render.py                # Terminal + Markdown output, saving
|   +-- tracking/
|   |   +-- watchlist.py             # watchlist.toml read/write
|   |   +-- history.py               # Score history (data/_history/scores.csv)
|   |   +-- changes.py               # track_changes(): what moved since the last run
|   +-- vetting/
|   |   +-- red_flags.py             # Rule-based red flags over a report dict
|   |   +-- peers.py                 # Yahoo industry/sector peers + peer-relative valuation
|   |   +-- ownership.py             # 13F fund activity from the discover cache
|   |   +-- verdict.py               # Fair value range, signal flip prices
|   |   +-- vet.py                   # vet_ticker() orchestration
|   |   +-- render.py                # Terminal + Markdown output
|   +-- scoring/
|   |   +-- config.py                # Scoring configuration & presets
|   |   +-- dimensions.py            # Dimension scorers
|   |   +-- scorer.py                # StockScorer orchestrator
|   +-- utils/
|       +-- concurrency.py           # Thread-pool helper for multi-ticker commands
|       +-- financial.py             # Financial calculations
|       +-- dataframe_utils.py       # DataFrame helpers
|       +-- report.py                # Report formatting
|       +-- serialization.py         # JSON conversion
|       +-- toon_serializer.py       # TOON format serializer
|       +-- types.py                 # Type definitions
+-- examples/                        # Standalone usage scripts
|   +-- 01_basic_fetch.py
|   +-- 02_inspect_data.py
|   +-- 03_test_fundamentals.py
|   +-- 05_technical_analysis.py
|   +-- 06_test_error_handling.py
|   +-- 07_test_risk_metrics.py
|   +-- 08_test_valuation.py
+-- tests/
    +-- conftest.py                  # Offline fake Yahoo market fixture
    +-- test_backtest.py
    +-- test_cli.py
    +-- test_comparator.py
    +-- test_discovery.py
    +-- test_pipeline.py
    +-- test_portfolio.py
    +-- test_quant_methods.py
    +-- test_review.py
    +-- test_scorer.py
    +-- test_screening.py
    +-- test_toon_serializer.py
    +-- test_tracking.py
    +-- test_vetting.py
```

## Python API

The CLI is the primary interface. For direct library use:

```python
from src.pipeline import AnalysisOptions, analyze_ticker
from src.scoring import ScoringConfig

# Compute only (no files written)
bundle = analyze_ticker("AAPL", options=AnalysisOptions(scoring_config=ScoringConfig.value_investor()))
print(f"{bundle.scoring.composite_score:.0f}/100  ({bundle.scoring.signal})")
print(bundle.freshness_warnings)

# Compute and write report files
from src.reporting import ReportGenerator
report_data = ReportGenerator(output_dir="data").generate_full_report("AAPL", period="1y")

# Screen a universe
from src.screening import Screener, ScreenFilters, resolve_universe
universe = resolve_universe(["sp100"])
result = Screener().run(universe.tickers, ScreenFilters(min_market_cap=100e9), top_n=10)
for c in result.scored:
    print(c.ticker, c.scoring.composite_score, c.factor_rank)

# Vet one ticker (red flags, peers, 13F activity, fair value)
from src.vetting import render_text, vet_ticker
vet = vet_ticker("AAPL", peers=["MSFT", "GOOGL", "META"])
print(render_text(vet.to_dict()))
print([f.title for f in vet.red_flags])
```

## Data Organization

The project uses a two-tier data structure:

- **``cache/``** -- Ephemeral API responses, regenerated on demand, gitignored
- **``reports/``** -- Analysis outputs, version-controlled for historical tracking

This allows regenerating fresh data without losing analysis history, and enables Git-tracked evolution of trading signals over time.

## Development

Install all dev dependencies (linter, formatter, test runner, type checker):

```bash
pip install -e ".[all,dev]"
```

Before pushing, run lint + format in one pass:

```bash
ruff check src/ tests/ --fix && ruff format src/ tests/
```

Run the test suite:

```bash
pytest tests/ -q
```

CI (GitHub Actions) runs `ruff check`, `ruff format --check`, and `pytest` automatically on every push and pull request to ``main``.
