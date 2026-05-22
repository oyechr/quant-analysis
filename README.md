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

### Composite Scoring

- 0-100 score across four dimensions: Technical, Fundamental, Risk, Valuation
- Configurable presets: ``default``, ``value``, ``growth``, ``income``
- Scorecard output with strengths and concerns

### Report Generation

- JSON reports with complete data aggregation
- Markdown reports for human-readable analysis
- TOON reports for LLM-optimized input (Token-Oriented Object Notation)

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
| Deep dive on one stock | ``quant report TICKER`` |
| Screen / rank a watchlist | ``quant score T1 T2 T3 ...`` |
| Compare two candidates | ``quant compare T1 T2`` |
| Monitor during market hours | ``quant watch T1 T2`` |

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
|   +-- analysis/
|   |   +-- technical.py             # Technical indicators (finta)
|   |   +-- fundamental.py           # Fundamental metrics
|   |   +-- valuation.py             # DCF/DDM valuation & earnings analysis
|   |   +-- risk.py                  # Risk metrics & VaR
|   +-- comparison/
|   |   +-- comparator.py            # TickerComparator & PortfolioView
|   |   +-- formatters.py            # Table, Markdown, JSON, heatmap output
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
