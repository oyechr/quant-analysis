# Examples

The `quant` CLI covers day-to-day use (see the main README). This folder shows
the Python API behind it, for notebooks and your own scripts.

```bash
pip install -e ".[all]"            # from the repo root
python examples/python_api.py AAPL
```

[python_api.py](python_api.py) walks through the main entry points:

| Entry point | What it gives you | CLI equivalent |
|-------------|-------------------|----------------|
| `src.pipeline.analyze_ticker(ticker, fetcher, options)` | An `AnalysisBundle`: the report dict, the `ScoringResult`, and the technical, fundamental, risk and valuation analyzers. Writes no files. | `quant report` / `quant score` |
| `src.vetting.vet_ticker(ticker, fetcher, peers=...)` | A `VetResult`: score, red flags, peer valuation, fair value range, next steps. | `quant vet` |
| `src.screening.Screener(fetcher).run(tickers, top_n=...)` | A `ScreenResult`: every ticker factor-ranked, the top N fully scored. | `quant screen` |

`AnalysisOptions` picks what to compute (`include_context=False` skips holders,
analyst ratings and news) and the scoring preset (`ScoringConfig.value_investor()`,
`growth_investor()`, `income_investor()`). Data is cached under `data/`, shared
with the CLI.

The example runs in the test suite on a synthetic market (`tests/test_examples.py`),
so it stays in step with the code.
