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

# Error handling validation
python examples/06_test_error_handling.py

# Risk metrics (Sharpe, Sortino, VaR, drawdowns)
python examples/07_test_risk_metrics.py

# Valuation analysis (DCF, DDM, dividends, earnings)
python examples/08_test_valuation.py
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

**Command-Line Interface:**

```bash
# Basic usage (includes all analyses: technical, fundamental, risk, valuation)
python examples/04_generate_report.py AAPL

# Custom period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
python examples/04_generate_report.py TSLA --period 2y

# Exclude specific analyses (all included by default)
python examples/04_generate_report.py MSFT --exclude-technical
python examples/04_generate_report.py NVDA --exclude-fundamental --exclude-risk

# Output format options
python examples/04_generate_report.py GOOGL --format json
python examples/04_generate_report.py AMZN --format markdown

# Bypass cache (fetch fresh data)
python examples/04_generate_report.py META --no-cache

# Get help
python examples/04_generate_report.py --help
```

**Features:**

- Generating comprehensive stock reports (JSON + Markdown)
- Integrating multiple data sources
- Technical analysis with 16+ indicators (timing signals) - included by default
- Fundamental analysis with growth, margins, efficiency, quality scores - included by default
- Risk metrics (Sharpe, Sortino, VaR, drawdowns) - included by default
- Valuation analysis (DCF, DDM, dividends, earnings) - included by default
- All analyses optional via --exclude-X flags

**Output:**

```
data/TICKER/reports/
├── full_report.json              # Complete data aggregation
├── report.md                     # Human-readable summary report
├── technical_analysis.json       # Technical indicators & signals
├── technical_analysis.md         # Entry/exit timing signals
├── fundamental_analysis.json     # Growth, margins, efficiency metrics
├── fundamental_analysis.md       # Detailed fundamental analysis
├── risk_analysis.json            # Risk-adjusted returns & metrics
├── risk_analysis.md              # Detailed risk report
├── valuation_analysis.json       # DCF, DDM, intrinsic value
└── valuation_analysis.md         # Detailed valuation report
```

**Comprehensive Coverage:**

- Aggregates price data, fundamentals, earnings, holders, dividends, ratings, news
- Technical analysis: 16+ indicators (SMA, EMA, MACD, RSI, Bollinger Bands, etc.)
- Fundamental analysis: Growth rates, FCF metrics, margins, DuPont, quality scores
- Risk analysis: Sharpe/Sortino ratios, VaR, drawdowns, volatility, beta
- Valuation analysis: DCF/DDM models, dividend sustainability, earnings quality
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

### 06_test_error_handling.py - Error Handling

**Demonstrates:**

- Handling invalid tickers
- Graceful degradation with missing data
- Validation and fallback mechanisms
- Error reporting without crashes

**Use Case:** Validate robustness of data fetching and analysis modules

---

### 07_test_risk_metrics.py - Risk Analysis

**Demonstrates:**

- Calculating risk-adjusted return metrics:
  - **Sharpe Ratio:** Excess return per unit of total risk
  - **Sortino Ratio:** Excess return per unit of downside risk
  - **Calmar Ratio:** Return per unit of maximum drawdown
- Volatility measurements:
  - Historical volatility (annualized)
  - Downside deviation (negative returns only)
- Drawdown analysis:
  - Maximum drawdown and duration
  - Current drawdown status
- Value at Risk (VaR):
  - 95% and 99% confidence levels
  - Parametric and historical methods
- Market risk:
  - Beta calculation vs market index

**Output:**

- JSON report: `data/TICKER/reports/risk_analysis.json`
- Markdown report: `data/TICKER/reports/risk_analysis.md`

**Key Metrics:**

- Sharpe > 1.0 = good risk-adjusted returns
- Max drawdown = worst peak-to-trough decline
- VaR = potential loss at confidence level

---

### 08_test_valuation.py - Valuation Analysis

**Demonstrates:**

- Intrinsic value calculation:
  - **DCF (Discounted Cash Flow):** Free cash flow projection
  - **DDM (Dividend Discount Model):** Gordon Growth Model
- Dividend analysis:
  - Yield, growth rate, payout ratio
  - Coverage ratio and sustainability score
  - Consecutive payment years
- Earnings analysis:
  - EPS trends and growth (1Y, 3Y CAGR)
  - Earnings surprises and beat rate
  - Quality assessment (cash flow backing)
- Multi-currency support:
  - Automatic currency detection (USD, CAD, NOK, EUR, GBP)
  - Proper symbol formatting (kr, CA$, €, £)
- Fair value assessment:
  - Current price vs intrinsic value
  - Discount/premium percentage

**Output:**

- JSON report: `data/TICKER/reports/valuation_analysis.json`
- Markdown report: `data/TICKER/reports/valuation_analysis.md`

**Key Concepts:**

- DCF requires positive free cash flow
- DDM requires dividend payments
- Growth rate must be < discount rate
- Sustainability score based on payout, growth, consistency

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
      full_report.json          # Complete data aggregation
      report.md                 # Human-readable summary report
      technical_analysis.json   # Technical indicators & signals
      technical_analysis.md     # Detailed technical analysis
      fundamental_analysis.json # Growth, margins, efficiency metrics
      fundamental_analysis.md   # Detailed fundamental analysis
      risk_analysis.json        # Risk-adjusted returns & metrics
      risk_analysis.md          # Detailed risk analysis
      valuation_analysis.json   # DCF, DDM, intrinsic value
      valuation_analysis.md     # Detailed valuation analysis
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

**Completed Features:**

- ✅ Data fetching with intelligent caching
- ✅ Technical analysis (16+ indicators: SMA, EMA, MACD, RSI, Bollinger Bands, etc.)
- ✅ Fundamental analysis (growth rates, FCF metrics, margins, DuPont, Altman Z, Piotroski F)
- ✅ Risk analysis (Sharpe, Sortino, Calmar ratios, VaR 95/99, beta, drawdowns)
- ✅ Valuation analysis (DCF, DDM models, dividend sustainability, earnings quality)
- ✅ Comprehensive reporting (JSON + Markdown, 10 files per ticker)
- ✅ Multi-currency support (USD, CAD, NOK, EUR, GBP, JPY, SEK, DKK)
- ✅ All analyses included by default (opt-out via --exclude-X flags)

**Planned Enhancements:**

- Portfolio correlation and multi-ticker analysis
- Portfolio optimization (efficient frontier)
- Backtesting trading strategies
- Real-time data monitoring
- Interactive dashboards
- ML-based price forecasting
