# Quantitative Analysis Tool

A Python-based quantitative financial analysis tool for fetching market data and performing analytics.

## Features

### Data Fetching
- Historical price data via yfinance
- Multiple ticker support
- Configurable date ranges
- CSV caching

### Analytics (Planned)
- Basic statistics (returns, volatility, max drawdown)
- Trend analysis (SMA, EMA, Bollinger Bands, RSI, MACD)
- Risk metrics (Beta, Sharpe Ratio, Sortino Ratio)
- Portfolio correlation and simulations
- ML forecasting (optional)

### Visualization (Planned)
- Interactive charts
- Candlestick charts
- Correlation heatmaps
- Risk-return scatter plots

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```python
from src.data_fetcher import DataFetcher

# Fetch data
fetcher = DataFetcher()
data = fetcher.fetch_ticker("AAPL", period="1y")
```

## Project Structure

```
quant-analysis/
├── src/
│   ├── data_fetcher.py      # Data fetching module
│   ├── analytics.py          # Statistical calculations
│   ├── indicators.py         # Technical indicators
│   ├── risk_metrics.py       # Risk calculations
│   └── visualization.py      # Plotting functions
├── data/                     # Cached data
├── tests/                    # Unit tests
└── examples/                 # Example scripts
```
