# Quant Analysis - Examples

## Running Examples

Install dependencies first:
```bash
pip install -r requirements.txt
```

Run examples from the project root:

```bash
# Basic data fetching
python examples/01_basic_fetch.py

# Data inspection and validation
python examples/02_inspect_data.py
```

## Examples

### 01_basic_fetch.py
Demonstrates:
- Fetching single ticker data
- Getting ticker information/metadata
- Fetching multiple tickers at once
- Using custom date ranges
- Automatic caching

### 02_inspect_data.py
Demonstrates:
- Data quality checks
- Statistical summaries
- Missing value detection
- Quick comparison across multiple stocks

## Next Steps

After data fetching works:
1. Add basic analytics (returns, volatility)
2. Implement technical indicators
3. Add risk metrics
4. Build visualizations
