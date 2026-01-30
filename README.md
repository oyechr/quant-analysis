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
- **Momentum Indicators:** RSI, Stochastic Oscillator, Williams %R
- **Volatility Indicators:** Bollinger Bands, ATR, ADX
- **Volume Indicators:** OBV, VWAP, MFI
- **Statistical Summaries:** Price ranges, returns, volatility metrics
- Automated signal generation (buy/sell signals)
- Comprehensive technical reports (JSON + Markdown)

### Fundamental Analysis

- **Growth Metrics:** Revenue, Earnings, FCF growth (1Y, 3Y, 5Y CAGR)
- **Free Cash Flow Analysis:** FCF yield, FCF margin, FCF per share
- **Profitability Margins:** Gross, EBITDA, Operating, Net margins with trends
- **Efficiency Ratios:** Asset turnover, inventory turnover, receivables/payables, cash conversion cycle
- **DuPont Analysis:** ROE decomposition (Margin × Turnover × Leverage)
- **Quality Scores:** Altman Z-Score (bankruptcy risk), Piotroski F-Score (fundamental strength)
- Graceful handling of missing financial data
- Dual output format (JSON + Markdown)

### Valuation Analysis

- **DCF Valuation:** Discounted Cash Flow intrinsic value calculation
- **DDM Valuation:** Dividend Discount Model (Gordon Growth Model)
- **Dividend Analysis:** Yield, growth rate, payout ratio, coverage, sustainability scoring
- **Earnings Analysis:** EPS trends, surprises, quality assessment (cash flow backing)
- **Multi-Currency Support:** Automatic currency detection and formatting (USD, CAD, NOK, EUR, GBP)
- **Fair Value Assessment:** Discount/premium to intrinsic value

### Risk Analysis

- **Volatility Metrics:** Historical volatility, downside deviation
- **Risk-Adjusted Returns:** Sharpe ratio, Sortino ratio, Calmar ratio
- **Drawdown Analysis:** Maximum drawdown, current drawdown
- **Value at Risk (VaR):** 95% and 99% confidence levels (parametric and historical)
- **Market Risk:** Beta calculation, correlation with market indices

### Report Generation

- JSON reports with complete data aggregation
- Markdown reports for human-readable analysis
- Modular section-based architecture (10 section types)
- Separate detailed technical and fundamental analysis reports
- Automatic report versioning via Git
- Dual output strategy for both human and machine consumption

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

### Generate Comprehensive Report (Easiest)

```bash
# Generate full report with technical + fundamental analysis
python examples/04_generate_report.py AAPL

# Custom period
python examples/04_generate_report.py TSLA --period 2y

# Technical analysis only
python examples/04_generate_report.py MSFT --no-fundamental

# Markdown output only
python examples/04_generate_report.py NVDA --format markdown
```

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

### Fundamental Analysis

```python
from src.fundamental_analysis import FundamentalAnalyzer

# Fetch required data
info = fetcher.get_ticker_info("AAPL")
fundamentals = fetcher.fetch_fundamentals("AAPL")
price_data = fetcher.fetch_ticker("AAPL", period="1y")

# Analyze fundamentals
analyzer = FundamentalAnalyzer(info, fundamentals, price_data)
analyzer.calculate_all()

# Get summary with all metrics
summary = analyzer.get_summary()

# Format as markdown
markdown_report = analyzer.format_markdown()
```

### Generate Reports

```python
from src.report_generator import ReportGenerator

generator = ReportGenerator()

# Generate comprehensive report with technical and fundamental analysis
report = generator.generate_full_report(
    ticker="AAPL",
    period="1y",
    output_format="both",  # JSON + Markdown
    include_technical=True,    # Entry/exit timing signals
    include_fundamental=True   # Intrinsic value assessment
)
```

## Project Structure

```
quant-analysis/
├── src/
│   ├── data_fetcher.py           # Yahoo Finance data fetching with caching
│   ├── analysis/                 # Analysis modules
│   │   ├── technical.py          # Technical indicators (moved)
│   │   ├── fundamental.py        # Fundamental metrics (moved)
│   │   ├── valuation.py          # DCF/DDM valuation & earnings analysis
│   │   └── risk.py               # Risk metrics & VaR calculations
│   ├── reporting/                # Report generation
│   │   ├── generator.py          # Report aggregation
│   │   └── sections.py           # Modular section handlers
│   ├── utils/                    # Utility modules
│   │   ├── financial.py          # Financial calculations (CAGR, ratios)
│   │   ├── dataframe_utils.py    # DataFrame/Series helpers
│   │   ├── report.py             # Report formatting
│   │   ├── serialization.py      # JSON conversion
│   │   └── types.py              # Type definitions
│   ├── config.py                 # Configuration settings
│   └── (legacy files in transition)
├── data/                         # Data directory (organized by ticker)
│   └── TICKER/
│       ├── cache/                # Ephemeral API responses (gitignored)
│       │   ├── prices_1y_1d.csv
│       │   ├── info.json
│       │   ├── fundamentals.json
│       │   └── ...
│       └── reports/              # Generated analysis reports (tracked)
│           ├── full_report.json
│           ├── report.md
│           ├── technical_analysis.json
│           ├── technical_analysis.md
│           ├── fundamental_analysis.json
│           └── fundamental_analysis.md
├── examples/                     # Example usage scripts
│   ├── 01_basic_fetch.py
│   ├── 02_inspect_data.py
│   ├── 03_test_fundamentals.py
│   ├── 04_generate_report.py
│   ├── 05_technical_analysis.py
│   └── README.md                 # Detailed examples documentation
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
6. **06_test_error_handling.py** - Error handling validation
7. **07_test_risk_metrics.py** - Risk analysis (Sharpe, Sortino, VaR, drawdowns)
8. **08_test_valuation.py** - Valuation analysis (DCF, DDM, dividend/earnings)

Run from project root:

```bash
python examples/04_generate_report.py
```

## Development Roadmap

### Phase 1: Foundation ✅ (Completed)

- ✅ Data fetching with intelligent caching
- ✅ Technical analysis (16+ indicators)
- ✅ Fundamental analysis (growth, margins, efficiency, quality scores)
- ✅ Comprehensive report generation
- ✅ Type safety and error handling

### Phase 2: Risk & Valuation Analysis ✅ (Completed)

- ✅ Risk metrics (Beta, Sharpe, Sortino, Calmar, Max Drawdown, VaR)
- ✅ Valuation models (DCF, DDM)
- ✅ Dividend sustainability analysis
- ✅ Earnings quality assessment
- ✅ Multi-currency support
- Multi-ticker correlation analysis
- Portfolio optimization (efficient frontier)
- Relative strength and sector comparisons

### Phase 3: Advanced Features

- Backtesting framework for strategy validation
- Interactive visualizations (Plotly/Matplotlib)
- Configuration system for user parameters
- Enhanced error handling and validation

### Phase 4: Deployment & Tooling

- Unit test coverage
- CLI interface
- REST API wrapper
- Interactive dashboard (Streamlit)
- ML-based forecasting
- Real-time data streaming
