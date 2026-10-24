# quant-analysis

A command-line companion for stock picking with free Yahoo Finance data. It helps you:

- **find** candidates in an index or in what large funds are buying;
- **vet** one ticker in a single screen: verdict, red flags, peers, fair value;
- **review** the portfolio you hold, and turn the review into concrete **rebalance** trades;
- **track** a watchlist and see what changed since the last run.

Everything is rule-based and explained in the output. It's built for a Norwegian investor (NOK base currency, Oslo listings, Nordnet's ASK and AF accounts), but works for any market Yahoo covers.

> These are rule-based suggestions from free data, not advice. The Buy/Hold/Sell bands are rules of thumb: the backtest found no edge in the price-based part of the score, and the fundamental part can't be backtested with Yahoo's data (see [`quant backtest`](#quant-backtest)).

## Quick start

Requires Python 3.14+.

```powershell
py install 3.14                  # Python install manager (Windows)
py -V:3.14 -m venv venv
.\venv\Scripts\Activate.ps1      # macOS/Linux: source venv/bin/activate
python -m pip install -U pip
pip install -e ".[all]"
```

Extras: `llm` (anthropic, openai; needed for `quant chat`), `viz` (matplotlib, seaborn; the heatmap in `quant compare`), `all` (both), `dev` (pytest, ruff, mypy, type stubs).

```bash
quant screen sp100 --top 10          # the best-scoring names in an index
quant vet EQNR.OL                    # one-screen verdict on a ticker
quant watchlist add AAPL --thesis "Services growth"
quant changes                        # what moved on the watchlist since last time
quant review                         # your holdings: Exit / Review / Trim / Hold / Add
```

## Which command

| Goal | Command |
|------|---------|
| Find candidates in an index | `quant screen sp500` |
| See what large funds are buying (13F) | `quant discover` |
| Quick verdict on one stock | `quant vet TICKER` |
| Full write-up of one stock | `quant report TICKER` |
| Ask questions about a stock | `quant chat TICKER` |
| Score or compare a few tickers | `quant score T1 T2`, `quant compare T1 T2` |
| What to do with the stocks you own | `quant review` |
| Turn the review into trades | `quant rebalance --cash N --candidates watchlist` |
| Follow names, and see what moved | `quant watchlist add T`, `quant changes` |
| How much to trust the signals | `quant backtest sp100` |

**Finding and vetting new ideas:**

```bash
quant screen sp500 --top 25 --config growth      # rank the index, fully score the top 25
quant screen discover                            # or rank the funds' consensus picks
quant vet NVDA                                   # verdict, red flags, peers, fair value
quant report NVDA && quant chat NVDA             # deep dive, then ask about the bear case
quant watchlist add NVDA --thesis "AI capex cycle" --stop 150
```

**Your portfolio:**

```bash
quant import-portfolio "~/Downloads/Beholdningstabell eksport*.csv" --label 12345678=ASK --label 87654321=AF
quant review --save
quant rebalance --cash 20000 --candidates watchlist
```

**Following up**, daily or weekly: `quant changes`.

## Commands

Global options go **before** the command: `quant --period 2y report AAPL`.

| Global option | Default | What it does |
|---------------|---------|--------------|
| `--period` | `1y` | Price history for analysis: `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y` |
| `--format` | `all` | Report files: `json`, `markdown`, `toon`, `all` |
| `--no-cache` | off | Fetch fresh data, ignoring the cache |
| `--output-dir` | `data` | Folder for the cache, reports and history |
| `-v` / `-q` | | Debug logging / errors only (the default shows warnings) |

Most commands take `--config default|value|growth|income` (the scoring preset) and `--workers N` (tickers fetched in parallel; keep it modest, since Yahoo rate-limits).

### Find

#### `quant screen`

Ranks every ticker in a universe on four factors, then runs the full analysis on the best `--top` (default 20).

```bash
quant screen sp500 --top 25 --config value
quant screen obx --exclude-sector Energy
quant screen nasdaq100 --sector Technology --min-mcap 50B
quant screen my_tickers.txt EQNR.OL DNB.OL     # a ticker file plus literal tickers
quant screen sp100 --add-to-watchlist 5        # put the 5 best on the watchlist
quant screen --list                            # the built-in universes
```

- **Universes:** `sp500`, `sp100`, `nasdaq100`, `obx` (from Nasdaq's and Wikipedia's lists, cached for 30 days); `discover` (the last `quant discover` picks); `watchlist`; a ticker file (one or more per line, `#` comments, or a CSV with a `ticker` column); or literal tickers. Mix them freely.
- **Stage 1, rank:** company info and a year of prices per ticker. Each is ranked against the others on value (earnings yield, book/price), quality (ROE, leverage), momentum (12-1 month return) and low volatility, as percentiles (100 = best).
- **Stage 2, score:** the full technical, fundamental, risk and valuation analysis for the top N.
- **Filters:**
  - `--sector` / `--exclude-sector` match a sector or industry substring, and can be repeated.
  - `--min-mcap` / `--max-mcap` (e.g. `500M`, `10B`) are in the universe's own currency: NOK for `obx`, and USD when it mixes currencies. `--currency` picks another.
  - `--min-volume` is in shares.
- **Saving:** results are saved to `data/_screens/` (`--no-save` to skip). The first `sp500` screen takes a few minutes; later runs use the cache.

#### `quant discover`

Finds patterns across the 13F filings of well-known funds (Berkshire Hathaway, ARK, Soros, Bridgewater, Renaissance, Pershing Square, Appaloosa, Icahn), from SEC EDGAR (free, no key). It compares each fund's two latest quarters to tell new, added, trimmed, held and exited positions apart. It then looks for four patterns: tickers held by several funds, sector clusters, several funds buying or selling the same name, and funds disagreeing.

```bash
quant --no-cache discover             # fetch the latest filings (about 30 s)
quant discover --min-overlap 3        # held by 3+ funds: the strongest consensus
quant discover --sector Technology
quant screen discover                 # then rank and score the consensus picks
```

- **Options:** `--min-overlap` (default 2), `--top` (default 20), `--sector`, `--enrich` (sector data for every holding, not just the top ones; slow), and `--list-sources`.
- **Refreshing:** 13F filings arrive about 45 days after each quarter (mid-February, mid-May, mid-August, mid-November), so the data is 1-4 months old. Refresh with `--no-cache` after those dates.
- **User-Agent:** SEC asks for one with contact details (`edgar_user_agent` in `config.json`).

### Vet

#### `quant vet`

A one-screen verdict on one ticker. It writes nothing to disk unless you pass `--save`.

```bash
quant vet EQNR.OL
quant vet AAPL --peers MSFT,GOOGL,META
quant vet EQNR.OL --peers AKRBP.OL,VAR.OL    # home-market peers
quant vet NVDA --config growth --save        # also writes data/NVDA/reports/vet.json + vet.md
quant vet AAPL --brief                       # verdict, key facts and next steps only
```

It opens with `VERDICT: Look deeper / Watch / Pass` and the reasons:

- **Pass:** a high-severity red flag or a Sell signal.
- **Look deeper:** a Buy signal with at least medium confidence.
- **Watch:** everything else.

The sections that follow:

- **Red flags:** Beneish M-Score, Altman Z distress, repeated negative free cash flow, ongoing share dilution (a one-off issuance, such as a merger, is medium), uncovered dividend, weak interest cover, stale statements, low data coverage, and stale prices.
- **Peer valuation:** P/E, forward P/E, EV/EBITDA, P/S, P/B and FCF yield against the peer median, with percentiles.
  - **Choosing peers:** your `--peers`; otherwise Yahoo's industry list, topped up from its sector list. Only companies within 0.1x-10x of the ticker's market cap are kept, and other listings of the same company are dropped.
  - **Home-market peers:** Yahoo's lists are mostly US companies, so use `--peers` for those.
  - **P/E against peers:** with 4 or more peers that have a P/E, the P/E is judged against their median, so `vet`'s score can differ slightly from `report`'s.
- **Signals:** post-earnings drift, and relative strength against the home index.
- **Fund activity:** which tracked funds hold the ticker and what they did last quarter. This needs the cache from `quant discover`.
- **What would change the verdict:**
  - analyst targets and a fair value range (DCF, Monte Carlo, DDM);
  - the price at which valuation alone would move the signal one band;
  - trade levels.
- **Strengths, concerns and next steps.**

#### `quant report`

The full write-up of one ticker: a scorecard printed, and JSON, Markdown and TOON files in `data/TICKER/reports/`.

```bash
quant report AAPL
quant --period 2y report EQNR.OL --config income
quant --format toon report MSFT --exclude-technical
```

`--exclude-technical`, `--exclude-fundamental`, `--exclude-risk` and `--exclude-valuation` leave sections out.

#### `quant score` and `quant compare`

```bash
quant score AAPL MSFT TSLA --config growth     # one summary row per ticker
quant compare AAPL MSFT GOOGL                  # side by side, with return correlation
quant compare AAPL MSFT --weights 0.6,0.4      # plus a portfolio view
quant compare EQNR BP --save-chart data/corr.png
```

`compare` flags pairs that move together (correlation above 0.8) and hedges (below -0.3), and suggests inverse-volatility weights.

#### `quant chat`

A conversation about one ticker with an LLM that has the full report in context. If there's no report yet, one is generated first.

```bash
quant chat EQNR.OL
quant chat AAPL --model claude-opus-5-5
quant chat MSFT --no-intro            # skip the opening brief
quant --no-cache chat TSLA            # fresh data first
```

- **Context:** the model also sees the last 12 rows of the ticker's score history. It sees peer valuation if `quant vet TICKER --save` has been run.
- **In-session commands:** `/refresh` re-fetches the data and rebuilds the report, `/clear` resets the conversation, `/help`, and `/quit`.
- **Setup:** it needs an Anthropic or OpenAI key, or a free GitHub Models token, in `config.json` (see [Your files](#your-files)). `--debug-context` prints what the model is sent.

### Your portfolio

#### `quant import-portfolio`

Combines Nordnet holdings exports, one file per account, into `portfolio/portfolio.csv`. Nordnet's API is closed to retail customers, so the export is the input. In Nordnet's web app, download the holdings list for each account, then run:

```bash
quant import-portfolio "~/Downloads/Beholdningstabell eksport*.csv" --label 12345678=ASK --label 87654321=AF
quant import-portfolio "~/Downloads/Beholdningstabell eksport*.csv" --verify   # check each ticker on Yahoo
```

- **Exports:** both formats are read, `Beholdningstabell eksport, kontono. N, date.csv` and the older `aksjelister_konto-N_date.csv`. Quote the pattern, since the names have spaces.
- **Tickers:** the exports have names but no tickers, so `portfolio/tickers.csv` (`name,ticker`) maps them to Yahoo tickers. Unmapped names are listed so you can add them and rerun.
- **Accounts:** label them ASK or AF with `--label`, so `review` and `rebalance` can handle tax.
- **Updating:** rerun the import whenever your holdings change.

#### `quant review`

Vets every holding, values them in NOK (`--base` for another currency), and gives each an action.

```bash
quant review
quant review --config value --save     # also writes portfolio/review.json + review.md
```

| Action | Rule |
|--------|------|
| Exit | A Sell or Strong Sell signal |
| Review | A high-severity red flag with a Hold or Buy signal. Altman and Beneish have known false positives, so for a stock you own the flag means "look into it", not "sell" |
| Trim | The weight is at least 1.5x its target and 2+ points above it, or the holding moves with a larger one (weekly correlation of 0.80 or more) |
| Add | `vet` says Look deeper, the weight is below target, and it doesn't overlap a larger holding |
| Hold | Everything else. Funds are only ever Trim or Hold |
| Check | No price data, usually a wrong ticker in `portfolio/tickers.csv` |

- **The table:** each holding's weight, its share of the portfolio's risk, its target, gain, score, verdict and main reason.
- **The portfolio view:**
  - volatility, and beta against Oslo (OSEBX) and the world (ACWI);
  - the effective number of positions, by value and by risk, and the top-5 and top-10 weights;
  - the sector, country and currency mix, as share of value and share of risk;
  - factor tilts, and the pairs of holdings that move together.
- **Targets** are equal risk contribution, within your limits (see [How the numbers work](#portfolio-risk-and-targets)).

#### `quant rebalance`

Runs `review`, then turns its actions into trades, in this order:

1. Sell Exits in full.
2. Leave Review and Check holdings alone.
3. Trim down to the target, and cut any position above the position limit.
4. If a sector is above its limit, sell its lowest-scoring stocks.
5. Buy Add holdings up to their target, with `--cash` plus what the sales raised.
6. Buy candidates (`--candidates watchlist`, or tickers) that `vet` calls Look deeper and that don't move with a holding: best score first, at most `max_new`, each at the median target weight.
7. Round to whole shares and drop trades under `min_trade` (Exits are kept).

```bash
quant rebalance                                       # trades from the review alone
quant rebalance --cash 50000 --candidates watchlist   # new money and new names
quant rebalance --candidates AAPL,MSFT --save         # writes portfolio/rebalance.json + .md
```

- **The output:**
  - a summary line: sales, buys, cash left, and the net estimated AF tax;
  - the trades table, with an account for each trade;
  - before and after: volatility, betas, effective positions, and the sector, country and currency mix;
  - the trades that weren't made, and why.
- **Accounts:**
  - Sales come from ASK first, where gains are tax-free.
  - A sale in AF shows the estimated tax at 37.84% of the gain. A loss shows as negative, because it's deductible against gains at the same rate.
  - ASK only takes shares in EEA companies, so buys are marked "ASK or AF" or "AF only (not EEA)".
- **Not included:** trading costs and spreads.

### Track

#### `quant watchlist`

```bash
quant watchlist add EQNR.OL --thesis "Cheap vs peers if oil holds" --target 450 --stop 380
quant watchlist add AAPL MSFT
quant watchlist add EQNR.OL --stop 390       # update one field; the rest is kept
quant watchlist rm MSFT
quant watchlist ls                           # with each ticker's last recorded score
```

The list lives in `watchlist.toml` (`--file` for another file). Target and stop are prices in the listing currency.

#### `quant changes`

Rescores the watchlist (or the tickers given) and compares each one with its last run from an earlier day, on the same preset. Tickers with something worth a look come first:

- a signal change, or a score move of 3+ points (with the dimensions that moved 5+);
- red flags that appeared or cleared;
- a price within 5% of, or past, the target or stop;
- earnings in the next 14 days.

```bash
quant changes
quant changes EQNR.OL AAPL --config value
```

- **Score history:** every scoring command (`report`, `score`, `vet`, `screen`, `changes`, `review` and `rebalance`) adds a row per ticker to `data/_history/scores.csv`. A later run the same day replaces the earlier one.
- **Comparable scores:** `vet` stores its score before the peer adjustment, so rows from every command compare like with like.

#### `quant watch`

Rescores tickers on a timer during market hours, and writes nothing to disk. For a daily check, use `quant changes`.

```bash
quant watch AAPL MSFT --interval 60
quant watch EQNR.OL --interval 300 --count 5
```

### Trust

#### `quant backtest`

How well did the price-based signals predict the next months?

```bash
quant backtest sp100                         # 5 years; horizons 1, 3 and 6 months
quant backtest obx --years 3 --horizons 1,3
quant backtest watchlist --no-save
```

**Method:**
- At every month-end, each ticker is scored on the prices up to that day only: the technical and risk scores, their composite (with the real Buy/Hold/Sell bands), 12-1 momentum and low volatility.
- The returns over the next months are then compared with the home index.
- Results are written to `data/_backtests/`: JSON, Markdown, and a CSV of every ticker-month.

**What the output reports:**

| Table | What it says |
|-------|--------------|
| Rank IC | Correlation between the signal and the next return, averaged over months. Above about 0.03 is typical for a useful signal |
| Quintile spread | Return of the top fifth minus the bottom fifth |
| Hit rate | Share of months the top fifth beat the bottom fifth |
| Signal bands | Return against the index for each Buy/Hold/Sell band. Useful bands rise from Strong Sell to Strong Buy |

**Statistics:** intervals are 95%, with Newey-West errors because the windows overlap. A beta-adjusted section separates market exposure from stock picking.

**Findings (October 2021 to September 2026, sp100 and OBX):**
- **No edge in the composite.** The price-only composite has rank ICs between -0.04 and +0.02, and every interval includes zero. The bands don't rise from Sell to Buy; on sp100, Buy did worst. That is why the bands are documented as rules of thumb.
- **Low volatility lost** by about 5% over 3 months, beta-adjusted. That goes against the long-run evidence, so the risk score is unchanged for now.
- **Momentum** leaned positive, but within noise.

**Limits:**
- Fundamentals and valuation can't be tested: Yahoo serves restated statements with no publication dates.
- The universe is today's constituents (survivorship bias).
- Trades are at the close, with no costs.

## How the numbers work

### Composite score

Each ticker gets a score from 0 to 100, built from four dimensions, weighted by preset (`default`, `value`, `growth`, `income`):

- **Technical:** trend (SMA, EMA, MACD), momentum (RSI, Stochastic, Williams %R), volatility (Bollinger, ATR, ADX), and volume (OBV, VWAP, MFI).
- **Fundamental:** Piotroski F-Score, Altman Z, Beneish M, accruals, growth (revenue, earnings and FCF CAGR), margins, and ROE.
  - Altman's original Z is used for manufacturers (industrials, materials, energy), and Z'' for everyone else.
  - Banks and insurers skip the cash-flow measures and Altman.
- **Risk:** volatility, downside deviation, Sharpe, Sortino and Calmar ratios, drawdowns, VaR at 95% and 99%, and beta and alpha against the home index (OSEBX for `.OL`, FTSE 100 for `.L`, DAX for `.DE`, the S&P 500 for US listings).
- **Valuation:** DCF against the price, P/E, PEG, FCF yield, dividend sustainability, and earnings quality. Banks and insurers skip DCF and FCF yield.

**Bands:** Strong Buy is 80+, Buy 65-80, Hold 50-65, Sell 35-50, and Strong Sell below 35. Read a band as a summary of the score, not as a forecast.

### Valuation

- **DCF:** two stages.
  - FCF growth starts at the 3-year history, clamped to -10% to +20%, and fades to 2.5% over 10 years. A terminal value follows.
  - The discount rate is a WACC: CAPM cost of equity (the risk-free rate from `config.json`, a 5% equity premium, and a Blume-adjusted beta), plus after-tax debt.
  - Net debt comes from the balance sheet.
- **Reverse DCF:** the starting growth the price implies.
- **Monte Carlo:** the same model with varied inputs. **DDM:** Gordon growth, with growth capped at 4%.
- **Known limit:** the latest FCF is the base, so cyclicals at a capex peak look expensive.

### Currencies

Many companies report in one currency and trade in another; most Oslo energy names report in USD.

- **Statements** are converted into the listing currency at the latest Yahoo FX rate before any analysis.
- **Yahoo's own ratios** are corrected the same way, both for the ticker and for its peers.
- **London listings** trade in pence and are handled.
- **Portfolio values** are in the base currency (NOK by default).

### Portfolio risk and targets

- **Returns:** risk, beta and correlations use two years of weekly returns in the base currency.
  - Prices are converted with the daily FX rate, because a NOK investor carries the currency risk.
  - Returns are weekly because markets in different time zones close at different times, which makes daily correlations look too low.
  - The covariance is shrunk towards constant correlation (Ledoit-Wolf).
  - A holding with less than 18 months of history is left out of the risk numbers and named.
- **Risk share:** a holding's share of the portfolio's variance. The shares sum to 100%.
- **Factor tilts:** weighted medians over the stocks held: earnings yield (value), ROE (quality), 12-1 month return (momentum) and volatility. They describe the portfolio; they aren't regression loadings.
- **Targets:** equal risk contribution, meaning every holding contributes the same share of risk. Unlike inverse volatility, this accounts for correlation.
  - Set first: Exits get 0, Review holdings and short histories keep their weight, and your own targets take their share. The rest is shared out by equal risk.
  - Caps: positions up to 10% and sectors up to 35% by default (funds are exempt). What a cap removes goes to the other holdings.
  - A broad ETF moves with everything, so equal risk keeps it small. Give it a fixed target in `targets.toml` if you want more.

### Data and caching

- **Source:** everything comes from Yahoo Finance through yfinance: prices, statements, earnings, dividends, holders, analyst ratings and news.
- **Cache expiry:** prices 12 hours, company info 24 hours, statements 7 days, and so on. Override this in `config.json`.
- **When Yahoo fails:** the expired cache is used, and the output says so.
- **Stale data**, such as a last price bar 9 days old, is flagged in reports and red flags.

## Your files

| File | What | In git? |
|------|------|---------|
| `config.json` | Settings and API keys (below) | No |
| `watchlist.toml` | The watchlist (`quant watchlist`) | No |
| `portfolio/portfolio.csv`, `tickers.csv` | Your holdings and the name-to-ticker map (`quant import-portfolio`) | No |
| `portfolio/targets.toml` | Limits and per-ticker targets for `review` and `rebalance` (optional) | No |
| `portfolio/review.*`, `rebalance.*` | Saved with `--save` | No |
| `data/` | The cache, reports, score history, screens and backtests | No |

**`config.json`** (all keys optional):

```json
{
    "risk_free_rate": 0.04,
    "benchmark_ticker": "^GSPC",
    "benchmark_by_suffix": {".OL": "OBX.OL"},
    "cache_ttl_hours": {"fundamentals": 336, "prices": 6},
    "edgar_user_agent": "PersonalResearch you@email.com",
    "llm_model": "claude-haiku-5-5",
    "llm_anthropic_api_key": "sk-ant-...",
    "llm_github_token": "ghp_..."
}
```

- **Risk and benchmarks:**
  - `risk_free_rate` is a decimal (0.04 = 4%). It's used for Sharpe, Sortino, alpha and the DCF.
  - `benchmark_ticker` is the index for US and unmapped listings.
  - `benchmark_by_suffix` overrides the built-in exchange-to-index map.
- **Cache:** `cache_ttl_hours` sets the maximum age per resource (`prices`, `info`, `earnings`, `analyst_ratings`, `dividends`, `fundamentals`, `holders`, `universe`, `industry`). `0` means never expire.
- **Chat:**
  - `llm_model` picks the model: `claude-*` uses Anthropic, and `gpt-*` uses OpenAI or GitHub Models. Without it, chat uses `gpt-4.1` through GitHub Models. For Anthropic, `claude-haiku-5-5` is the cheap option and `claude-opus-5-5` the most thorough.
  - The key comes from `llm_anthropic_api_key` or `llm_openai_api_key`.
  - Alternatively, `llm_github_token` gives free access through [GitHub Models](https://github.com/marketplace/models).

**`portfolio/targets.toml`:**

```toml
[limits]
max_position = 0.10    # of the portfolio
max_sector = 0.35
cash_reserve = 0       # base currency, kept out of buys
min_trade = 2000       # base currency; smaller trades are dropped
max_new = 3            # new names per rebalance

[ticker."XYZ.DE"]      # e.g. a broad ETF
target = 0.10          # a fixed target; or max = 0.05 for a cap of its own
```

**`watchlist.toml`:**

```toml
["EQNR.OL"]
thesis = "Cheap vs peers if oil holds"
added = 2026-10-22
target = 450.0
stop = 380.0
```

**`data/` layout:** `data/TICKER/cache/` (API responses) and `data/TICKER/reports/` (from `report` and `vet --save`). Shared folders: `_history/scores.csv`, `_screens/`, `_backtests/`, `_discovery/` (13F filings and results), `_universes/`, and `_peer_groups/`. Delete any of them to start fresh.

Report files come as JSON, Markdown and [TOON](https://github.com/toon-format/spec). TOON is a compact format for LLM input, and leaves out the news section.

## Development

```bash
pip install -e ".[all,dev]"
ruff check src tests && ruff format --check src tests && mypy src --ignore-missing-imports && pytest tests -q
```

These are the same checks CI runs. The tests run offline against a fake Yahoo market. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the code layout and the Python API, and [docs/ROADMAP.md](docs/ROADMAP.md) for the plan and the design notes behind each phase.
