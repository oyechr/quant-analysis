# Quantitative Analysis Tool

A Python-based quantitative financial analysis tool for fetching market data, performing technical and fundamental analysis, and generating comprehensive stock reports.

## Features

### Data Fetching

- Historical price data via Yahoo Finance (yfinance)
- Company fundamentals and financial statements
- Earnings data and institutional holdings
- Dividend history and analyst ratings
- Recent news articles
- Intelligent caching system (cache vs reports separation)

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

- **DCF Valuation:** Discounted Cash Flow intrinsic value calculation
- **DDM Valuation:** Dividend Discount Model (Gordon Growth Model)
- **Dividend Analysis:** Yield, growth rate, payout ratio, coverage, sustainability scoring
- **Earnings Analysis:** EPS trends, surprises, quality assessment (cash flow backing)
- **Multi-Currency Support:** Automatic currency detection and formatting (USD, CAD, NOK, EUR, GBP)

### Risk Analysis

- **Volatility Metrics:** Historical volatility, downside deviation
- **Risk-Adjusted Returns:** Sharpe ratio, Sortino ratio, Calmar ratio
- **Drawdown Analysis:** Maximum drawdown, current drawdown
- **Value at Risk (VaR):** 95% and 99% confidence levels (parametric and historical)
- **Market Risk:** Beta calculation

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
- Configurable presets: ``default``, ``value``, ``growth``, ``income``
- Scorecard output with strengths and concerns

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

```bash
pip install -e .
```

### Requirements

- Python 3.11+
- yfinance, pandas, numpy
- finta (technical analysis)
- lxml, matplotlib, seaborn

## CLI Reference

### ``quant report`` -- Single-ticker deep dive

Generates a full report with scorecard for one ticker. Prints dimension scores, strengths, and concerns. Saves JSON, Markdown, and TOON files.

```bash
quant report AAPL
quant report EQNR --period 2y
quant report MSFT --exclude-technical --no-cache
quant report AAPL --format toon
```

Options:
- ``--exclude-technical / --exclude-fundamental / --exclude-risk / --exclude-valuation``

### ``quant score`` -- Multi-ticker screening table

Scores one or more tickers and prints a compact summary table. Use this for screening and ranking a watchlist.

```bash
quant score AAPL MSFT TSLA
quant score NVDA AMD --config growth
quant score EQNR BP --config value
```

Options:
- ``--config [default|value|growth|income]`` -- scoring weight preset

### ``quant compare`` -- Side-by-side comparison

Compares two or more tickers across scores, relative valuation, key metrics, and return correlation. Use this for head-to-head evaluation before a buy decision.

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
- Pipe discovery results into scoring: take the top tickers and run ``quant score``

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

Re-scores tickers on a timer. Useful for monitoring during market hours.

```bash
quant watch AAPL MSFT --interval 60
quant watch EQNR --interval 300 --count 5
```

Options:
- ``--interval`` -- refresh interval in seconds (default: 300)
- ``--count`` -- number of iterations before exiting (default: 0 = infinite)

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
| ``-v / --verbose`` | off | Enable debug logging |
| ``-q / --quiet`` | off | Suppress INFO logging |

## When to Use Which Command

| Goal | Command |
|------|---------|
| Discover new investment ideas | ``quant discover`` |
| Deep dive on one stock | ``quant report TICKER`` |
| Ask follow-up questions / interrogate a stock | ``quant chat TICKER`` |
| Screen / rank a watchlist | ``quant score T1 T2 T3 ...`` |
| Compare two candidates | ``quant compare T1 T2`` |
| Monitor during market hours | ``quant watch T1 T2`` |

### Recommended Workflow: Discovery → Analysis

```bash
# Step 1: What are the whales buying? (run after new 13F filings appear)
quant --no-cache discover --min-overlap 3

# Step 2: Note the top consensus tickers, score them
quant score AAPL NVDA AMZN MSFT BAC --config growth

# Step 3: Deep dive on the highest-scoring ticker
quant report NVDA

# Step 4: Compare your top 2-3 candidates
quant compare NVDA AMD AVGO

# Step 5: Ask the LLM about risks and thesis
quant chat NVDA
# > "What's the bear case? Is the valuation stretched?"

# Step 6: Monitor your picks
quant watch NVDA AAPL MSFT --interval 300
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
|   +-- data_fetcher.py              # Yahoo Finance data fetching with caching
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
|   |   +-- sources/
|   |       +-- base.py              # PortfolioSource ABC (pluggable)
|   |       +-- edgar_13f.py         # SEC EDGAR 13F source (free)
|   +-- reporting/
|   |   +-- generator.py             # Report aggregation
|   |   +-- sections.py              # Modular section handlers
|   +-- scoring/
|   |   +-- config.py                # Scoring configuration & presets
|   |   +-- dimensions.py            # Dimension scorers
|   |   +-- scorer.py                # StockScorer orchestrator
|   +-- utils/
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
    +-- test_cli.py
    +-- test_comparator.py
    +-- test_discovery.py
    +-- test_scorer.py
    +-- test_toon_serializer.py
```

## Python API

The CLI is the primary interface. For direct library use:

```python
from src.reporting import ReportGenerator
from src.scoring import StockScorer

generator = ReportGenerator(output_dir="data")
report_data = generator.generate_full_report(ticker="AAPL", period="1y")

scorer = StockScorer()
result = scorer.score(report_data)
print(f"{result.composite_score:.0f}/100  ({result.signal})")
```

## Data Organization

The project uses a two-tier data structure:

- **``cache/``** -- Ephemeral API responses, regenerated on demand, gitignored
- **``reports/``** -- Analysis outputs, version-controlled for historical tracking

This allows regenerating fresh data without losing analysis history, and enables Git-tracked evolution of trading signals over time.

## Development

Install all dev dependencies (linter, formatter, test runner, type checker):

```bash
pip install -e ".[dev,llm]"
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
