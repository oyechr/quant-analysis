# Quant Analysis - Examples

Demonstration scripts showing how to use the quantitative analysis toolkit.

## Installation

Install dependencies first:

```bash
pip install -r requirements.txt
```

## Running Examples

Run all examples from the project root directory:

```bash
# Basic data fetching and caching
python examples/01_basic_fetch.py

# Data inspection and validation
python examples/02_inspect_data.py

# Company fundamentals (earnings, financials, holders)
python examples/03_test_fundamentals.py

# Comprehensive report generation
python examples/04_generate_report.py

# Technical analysis with indicators
python examples/05_technical_analysis.py
```

## Example Details

### 01_basic_fetch.py - Data Fetching Basics

**Demonstrates:**

- Fetching historical price data for a single ticker
- Getting company information and metadata
- Fetching multiple tickers simultaneously
- Using custom date ranges
- Automatic CSV caching system

**Output:**

- Cached price data: `data/TICKER/cache/prices_1y_1d.csv`
- Ticker info: `data/TICKER/cache/info.json`

---

### 02_inspect_data.py - Data Quality Checks

**Demonstrates:**

- Loading cached data
- Statistical summaries (mean, std, min, max)
- Missing value detection
- Data quality validation
- Quick comparison across multiple stocks

**Use Case:** Verify data integrity before analysis

---

### 03_test_fundamentals.py - Company Fundamentals

**Demonstrates:**

- Fetching financial statements (income, balance sheet, cash flow)
- Earnings history and estimates
- Institutional and mutual fund holdings
- Dividend history and stock splits
- Analyst ratings and price targets
- Recent news articles

**Output:**

- Cached JSON files in `data/TICKER/cache/`

---

### 04_generate_report.py - Comprehensive Reports

**Demonstrates:**

- Generating full stock reports (JSON + Markdown)
- Integrating multiple data sources
- Optional technical analysis inclusion
- Report section modularity

**Output:**

```
data/TICKER/reports/
├── full_report.json           # Complete data aggregation
├── report.md                  # Human-readable report
├── technical_analysis.json    # Technical indicators (if enabled)
└── technical_analysis.md      # Detailed analysis (if enabled)
```

**Features:**

- Aggregates price data, fundamentals, earnings, holders, dividends, ratings, news
- Optional technical analysis with 13+ indicators
- Markdown formatting for readability
- Automatic cache/report separation

---

### 05_technical_analysis.py - Technical Indicators

**Demonstrates:**

- Calculating technical indicators:
  - **Trend:** SMA (20, 50, 200), EMA (12, 26), MACD
  - **Momentum:** RSI, Stochastic Oscillator
  - **Volatility:** Bollinger Bands, ATR
  - **Volume:** OBV, VWAP
- Generating trading signals (buy/sell)
- Getting latest indicator values
- Formatting for analysis reports

**Output:**

- JSON summary: `data/TICKER/reports/technical_analysis.json`
- Console display of all indicators and signals

**Key Concepts:**

- Requires 1 year of data for 200-day SMA
- Automatic signal generation (overbought/oversold, crossovers)
- NaN handling for indicators requiring warmup periods

---

## Data Organization

Examples write to structured directories:

```
data/
  TICKER/
    cache/                      # Ephemeral (gitignored)
      prices_1y_1d.csv          # Historical price data
      info.json                 # Company metadata
      fundamentals.json         # Financial statements
      earnings.json
      holders.json
      dividends.json
      analyst_ratings.json
      news.json
    reports/                    # Analysis outputs (tracked)
      full_report.json          # Comprehensive report
      report.md                 # Markdown report
      technical_analysis.json   # Technical indicators
      technical_analysis.md     # Detailed technical report
```

**Why separate cache and reports?**

- Cache can be regenerated anytime (use_cache=False)
- Reports track analysis conclusions over time
- Git version control for trading signals and insights

## Workflow

**Typical Usage Pattern:**

1. **Fetch Data** (01, 03) → Populate cache/
2. **Validate Data** (02) → Check quality
3. **Generate Reports** (04) → Create analysis in reports/
4. **Technical Analysis** (05) → Deep-dive indicators
5. **Review & Commit** → Git track valuable insights

**Re-running:**

- Cache automatically reused (fast subsequent runs)
- Reports overwritten each run
- Delete `cache/` to force fresh data

## Advanced Usage

### Custom Periods

```python
# In any example, modify:
fetcher.fetch_ticker("AAPL", period="2y")  # 2 years
fetcher.fetch_ticker("AAPL", start="2020-01-01", end="2021-12-31")
```

### Disable Caching

```python
# Force fresh data:
fetcher.fetch_ticker("AAPL", use_cache=False)
```

### Multiple Tickers

```python
tickers = ["AAPL", "MSFT", "GOOGL"]
for ticker in tickers:
    generator.generate_full_report(ticker, include_technical=True)
```

## Next Steps

Potential enhancements:

- Risk metrics (Sharpe ratio, max drawdown)
- Portfolio correlation analysis
- Backtesting trading strategies
- Real-time data monitoring
- Interactive dashboards
- ML-based price forecasting
