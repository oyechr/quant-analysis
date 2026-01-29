# Quantitative Analysis Tool

A Python-based quantitative financial analysis tool for fetching market data, performing technical analysis, and generating comprehensive stock reports.

## Features

### Data Fetching

- Historical price data via Yahoo Finance (yfinance)
- Company fundamentals and financial statements
- Earnings data and institutional holdings
- Dividend history and analyst ratings
- Recent news articles
- Intelligent caching system (cache vs reports separation)
- Multiple ticker support with configurable date ranges

### Technical Analysis

- **Trend Indicators:** SMA, EMA, MACD
- **Momentum Indicators:** RSI, Stochastic Oscillator
- **Volatility Indicators:** Bollinger Bands, ATR
- **Volume Indicators:** OBV, VWAP
- Automated signal generation (buy/sell signals)
- Comprehensive technical reports

### Report Generation

- JSON reports with complete data aggregation
- Markdown reports for human-readable analysis
- Modular section-based architecture
- Separate detailed technical analysis reports
- Automatic report versioning via Git

### Code Quality

- Modular, extensible architecture
- Abstract base classes for consistency
- Helper method extraction for code reuse
- Type hints and comprehensive logging
- Serialization utilities for data conversion

## Installation

```bash
pip install -r requirements.txt
```

### Requirements

- Python 3.11+
- yfinance
- pandas
- numpy
- ta (technical analysis library)

## Quick Start

### Basic Data Fetching

```python
from src.data_fetcher import DataFetcher

fetcher = DataFetcher()

# Fetch price data
price_data = fetcher.fetch_ticker("AAPL", period="1y")

# Get company info
info = fetcher.get_ticker_info("AAPL")

# Get fundamentals
fundamentals = fetcher.fetch_fundamentals("AAPL")
```

### Technical Analysis

```python
from src.technical_analysis import TechnicalAnalyzer

analyzer = TechnicalAnalyzer(price_data)
analyzer.calculate_all_indicators()

# Get latest values
latest = analyzer.get_latest_values()

# Generate trading signals
signals = analyzer.generate_signals()

# Get complete summary
summary = analyzer.get_summary()
```

### Generate Reports

```python
from src.report_generator import ReportGenerator

generator = ReportGenerator()

# Generate comprehensive report with technical analysis
report = generator.generate_full_report(
    ticker="AAPL",
    period="1y",
    output_format="both",  # JSON + Markdown
    include_technical=True
)
```

## Project Structure

```
quant-analysis/
├── src/
│   ├── data_fetcher.py           # Yahoo Finance data fetching with caching
│   ├── technical_analysis.py     # Technical indicators and signal generation
│   ├── report_generator.py       # Report aggregation and formatting
│   ├── report_sections.py        # Modular report section handlers
│   ├── serialization.py          # DataFrame/JSON conversion utilities
│   └── types.py                  # Type definitions for documentation
├── data/                         # Data directory (organized by ticker)
│   └── TICKER/
│       ├── cache/                # Ephemeral API responses (gitignored)
│       │   ├── prices_1y_1d.csv
│       │   ├── info.json
│       │   └── ...
│       └── reports/              # Generated analysis reports (tracked)
│           ├── full_report.json
│           ├── report.md
│           ├── technical_analysis.json
│           └── technical_analysis.md
├── examples/                     # Example usage scripts
│   ├── 01_basic_fetch.py
│   ├── 02_inspect_data.py
│   ├── 03_test_fundamentals.py
│   ├── 04_generate_report.py
│   └── 05_technical_analysis.py
└── tests/                        # Unit tests (planned)
```

## Data Organization

The project uses a two-tier data structure:

- **cache/** - Ephemeral API responses, can be regenerated, gitignored
- **reports/** - Valuable analysis outputs, version-controlled for historical tracking

This separation allows:

- Regenerating fresh data without losing analysis history
- Git tracking of trading signals and analysis conclusions
- Clean separation of raw data vs insights

## Examples

See the `examples/` directory for detailed usage:

1. **01_basic_fetch.py** - Basic data fetching and caching
2. **02_inspect_data.py** - Data quality checks and validation
3. **03_test_fundamentals.py** - Fetching company fundamentals
4. **04_generate_report.py** - Comprehensive report generation
5. **05_technical_analysis.py** - Technical indicator calculation

Run from project root:

```bash
python examples/04_generate_report.py
```

## Future Enhancements

- Risk metrics (Beta, Sharpe Ratio, Sortino Ratio)
- Portfolio correlation analysis
- Backtesting framework
- Interactive visualizations
- ML-based forecasting
- Real-time data streaming
