"""
Analysis Pipeline

Fetch -> analyze -> score for a single ticker, with no file I/O.

ReportGenerator builds on this to write report files; the screener uses it
directly to score many tickers quickly. Keeping computation separate from
rendering means a screen of 50 tickers doesn't write 700 report files.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .analysis import FundamentalAnalyzer, TechnicalAnalyzer, ValuationAnalyzer
from .data_fetcher import DataFetcher
from .scoring import ScoringConfig, StockScorer
from .scoring.scorer import ScoringResult
from .utils.financial import trading_dates
from .utils.fx import (
    adjust_info_ratios,
    conversion_rate,
    convert_statements,
    needs_conversion,
)

logger = logging.getLogger(__name__)

# A daily bar older than this many calendar days suggests a halted/delisted
# ticker or a failed refresh (covers long weekends and exchange holidays).
STALE_PRICE_DAYS = 5


@dataclass
class AnalysisOptions:
    """What to compute for a ticker."""

    period: str = "1y"
    use_cache: bool = True
    include_technical: bool = True
    include_fundamental: bool = True
    include_risk: bool = True
    include_valuation: bool = True
    # Holders, analyst ratings, and news: shown in reports and chat, unused by
    # scoring. Skipping them saves three network calls per ticker when screening.
    include_context: bool = True
    scoring_config: Optional[ScoringConfig] = None


@dataclass
class AnalysisBundle:
    """
    Everything computed for one ticker.

    `report` is the JSON-serializable dict (same shape ReportGenerator has always
    produced). The analyzer objects are kept for markdown rendering.
    """

    ticker: str
    report: Dict[str, Any]
    scoring: Optional[ScoringResult] = None
    technical: Optional[TechnicalAnalyzer] = None
    fundamental: Optional[FundamentalAnalyzer] = None
    risk: Optional[tuple] = None  # (RiskMetrics, metrics dict, benchmark DataFrame)
    valuation: Optional[ValuationAnalyzer] = None
    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def freshness_warnings(self) -> List[str]:
        warnings: List[str] = (self.report.get("data_freshness") or {}).get("warnings", [])
        return warnings


class _RunFetcher:
    """
    Wraps a DataFetcher so each resource is fetched at most once per analysis run.

    Several analyses need the same prices and statements. With the cache enabled
    repeats are cheap disk reads, but with --no-cache each repeat was another
    network round-trip.
    """

    _MEMOIZED = frozenset(
        {
            "fetch_ticker",
            "get_ticker_info",
            "fetch_fundamentals",
            "fetch_earnings",
            "fetch_institutional_holders",
            "fetch_dividends",
            "fetch_analyst_ratings",
            "fetch_news",
        }
    )

    def __init__(self, fetcher: DataFetcher):
        self._fetcher = fetcher
        self._memo: Dict[tuple[Any, ...], Any] = {}
        # Set by analyze_ticker when statements are in another currency than the price
        self.statement_rate: Optional[float] = None
        self.converted_ticker: Optional[str] = None

    def __getattr__(self, name: str) -> Any:
        if name not in self._MEMOIZED:
            return getattr(self._fetcher, name)
        return self._memoized(name)

    def _memoized(self, name: str) -> Callable[..., Any]:
        attr = getattr(self._fetcher, name)

        def memoized(*args: Any, **kwargs: Any) -> Any:
            key_kwargs = tuple(sorted((k, v) for k, v in kwargs.items() if k != "use_cache"))
            key = (name, tuple(a.upper() if isinstance(a, str) else a for a in args), key_kwargs)
            if key not in self._memo:
                self._memo[key] = attr(*args, **kwargs)
            return self._memo[key]

        return memoized

    def fetch_fundamentals(self, ticker: str, use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """Statements, converted to the listing currency when a rate is set for this ticker."""
        raw: Dict[str, pd.DataFrame] = self._memoized("fetch_fundamentals")(
            ticker, use_cache=use_cache
        )
        if self.statement_rate is None or ticker.upper() != self.converted_ticker:
            return raw
        key = ("converted_fundamentals", ticker.upper(), self.statement_rate)
        if key not in self._memo:
            self._memo[key] = convert_statements(raw, self.statement_rate)
        converted: Dict[str, pd.DataFrame] = self._memo[key]
        return converted


def analyze_ticker(
    ticker: str,
    fetcher: Optional[DataFetcher] = None,
    options: Optional[AnalysisOptions] = None,
) -> AnalysisBundle:
    """
    Fetch data, run every requested analysis, and score one ticker.

    Individual analysis failures are logged and recorded in `bundle.errors`
    rather than raised, so one missing data source doesn't sink the whole run.
    """
    from .reporting.sections import (
        AnalystRatingsSection,
        DividendsSection,
        EarningsSection,
        FundamentalAnalysisSection,
        FundamentalsSection,
        HoldersSection,
        InfoSection,
        NewsSection,
        PriceDataSection,
        ReportSection,
        RiskAnalysisSection,
        TechnicalAnalysisSection,
    )

    options = options or AnalysisOptions()
    base_fetcher = fetcher or DataFetcher()
    run = _RunFetcher(base_fetcher)
    ticker = ticker.upper()
    use_cache = options.use_cache

    logger.info(f"Analyzing {ticker}")
    report: Dict[str, Any] = {
        "ticker": ticker,
        "generated_at": datetime.now().isoformat(),
        "period": options.period,
    }
    bundle = AnalysisBundle(ticker=ticker, report=report)

    def _run_step(name: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as e:
            logger.error(f"Error processing {name} for {ticker}: {e}")
            bundle.errors[name] = str(e)
            report[name] = None
            return None

    # Statements in another currency than the price (EQNR.OL: USD vs NOK) are
    # converted before any analysis sees them
    conversion = _run_step(
        "currency_conversion", lambda: _setup_statement_conversion(run, ticker, use_cache)
    )
    if conversion:
        report["currency_conversion"] = conversion

    # Data sections
    sections: Dict[str, ReportSection] = {
        "info": InfoSection(),
        "price_data": PriceDataSection(),
        "fundamentals": FundamentalsSection(),
        "earnings": EarningsSection(),
        "dividends": DividendsSection(),
    }
    if options.include_context:
        sections["holders"] = HoldersSection()
        sections["analyst_ratings"] = AnalystRatingsSection()
        sections["news"] = NewsSection()

    for section_name, section in sections.items():
        raw = _run_step(
            section_name,
            partial(section.fetch_data, run, ticker, use_cache=use_cache, period=options.period),
        )
        if raw is not None:
            report[section_name] = section.format_for_json(raw)
    if run.statement_rate is not None and report.get("info"):
        # Yahoo's P/S, EV/EBITDA and P/B can mix currencies for such tickers
        report["info"] = adjust_info_ratios(
            report["info"],
            run.statement_rate,
            book_equity=_latest_book_equity(run, ticker, use_cache),
        )

    # Technical (always 1y: the 200-day SMA needs a full year)
    if options.include_technical:
        tech_section = TechnicalAnalysisSection()
        bundle.technical = _run_step(
            "technical_analysis",
            lambda: tech_section.fetch_data(run, ticker, use_cache=use_cache, period="1y"),
        )
        if bundle.technical is not None:
            report["technical_analysis"] = tech_section.format_for_json(bundle.technical)

    # Fundamental
    if options.include_fundamental:
        fund_section = FundamentalAnalysisSection()

        def _fundamental() -> Any:
            price_data = run.fetch_ticker(ticker, period="1y", use_cache=use_cache)
            return fund_section.fetch_data(run, ticker, use_cache=use_cache, price_data=price_data)

        bundle.fundamental = _run_step("fundamental_analysis", _fundamental)
        if bundle.fundamental is not None:
            report["fundamental_analysis"] = fund_section.format_for_json(bundle.fundamental)

    # Risk
    if options.include_risk:
        risk_section = RiskAnalysisSection()

        def _risk() -> Any:
            price_data = run.fetch_ticker(ticker, period=options.period, use_cache=use_cache)
            return risk_section.fetch_data(
                run, ticker, use_cache=use_cache, price_data=price_data, period=options.period
            )

        bundle.risk = _run_step("risk_analysis", _risk)
        if bundle.risk is not None:
            report["risk_analysis"] = risk_section.format_for_json(bundle.risk)
            report["benchmark"] = (report["risk_analysis"].get("market_risk") or {}).get(
                "benchmark"
            )

    # Valuation
    if options.include_valuation:

        def _valuation() -> ValuationAnalyzer:
            analyzer = ValuationAnalyzer(
                ticker=ticker,
                ticker_info=report.get("info") or {},
                price_data=run.fetch_ticker(ticker, period="1y", use_cache=use_cache),
                fundamentals=run.fetch_fundamentals(ticker, use_cache=use_cache),
                earnings_data=run.fetch_earnings(ticker, use_cache=use_cache),
                dividends_data=_dividends_series(run.fetch_dividends(ticker, use_cache=use_cache)),
            )
            analyzer.analyze()
            return analyzer

        bundle.valuation = _run_step("valuation_analysis", _valuation)
        if bundle.valuation is not None:
            report["valuation_analysis"] = bundle.valuation.analyze()

    # Signals not used by the composite score (shown by `vet` and chat)
    if options.include_technical:
        signals = _run_step("signals", lambda: _signals(run, ticker, use_cache, bundle))
        if signals:
            report["signals"] = signals

    # Scoring
    def _score() -> ScoringResult:
        result = StockScorer(config=options.scoring_config).score(report)
        logger.info(f"Scoring complete: {result.composite_score:.1f}/100 ({result.signal})")
        return result

    bundle.scoring = _run_step("scoring", _score)
    if bundle.scoring is not None:
        report["scoring"] = bundle.scoring.to_dict()

    report["data_freshness"] = _freshness_summary(ticker, base_fetcher, report)
    return bundle


def _latest_book_equity(run: _RunFetcher, ticker: str, use_cache: bool) -> Optional[float]:
    """
    Common equity from the latest converted balance sheet (quarterly first, like
    Yahoo's own P/B), or None if not reported.
    """
    try:
        statements = run.fetch_fundamentals(ticker, use_cache=use_cache)
    except Exception as e:  # P/B then stays out of the peer comparison
        logger.warning(f"No balance sheet for {ticker}'s P/B: {e}")
        return None
    for name in ("balance_sheet_quarterly", "balance_sheet_annual"):
        sheet = statements.get(name)
        if sheet is None or sheet.empty:
            continue
        for row in ("Common Stock Equity", "Stockholders Equity"):
            if row in sheet.index:
                values = pd.to_numeric(sheet.loc[row], errors="coerce").dropna()
                if not values.empty:
                    return float(values.iloc[0])
    return None


def _setup_statement_conversion(
    run: _RunFetcher, ticker: str, use_cache: bool
) -> Optional[Dict[str, Any]]:
    """
    Set the run's statement conversion rate, if statements need one.

    Returns a description of the conversion (or of why it failed), or None when
    statements are already in the listing currency.
    """
    info = run.get_ticker_info(ticker, use_cache=use_cache) or {}
    statement_ccy = info.get("financial_currency")
    listing_ccy = info.get("currency")
    if not statement_ccy or not listing_ccy or not needs_conversion(statement_ccy, listing_ccy):
        return None

    result = conversion_rate(
        statement_ccy, listing_ccy, lambda symbol: run.latest_close(symbol, use_cache=use_cache)
    )
    description: Dict[str, Any] = {"from": statement_ccy, "to": listing_ccy}
    if result is None:
        description["rate"] = None
        description["error"] = f"no FX rate for {statement_ccy}->{listing_ccy}"
        logger.warning(f"{ticker}: {description['error']}; statement values left unconverted")
        return description

    rate, symbol = result
    run.statement_rate = rate
    run.converted_ticker = ticker.upper()
    description.update({"rate": rate, "fx_symbol": symbol})
    return description


def _signals(run: Any, ticker: str, use_cache: bool, bundle: AnalysisBundle) -> Dict[str, Any]:
    """Post-earnings drift (PEAD) and relative strength vs the home benchmark."""
    from .analysis.fundamental import calculate_pead_signal
    from .analysis.technical import calculate_relative_strength
    from .markets import benchmark_for

    prices = run.fetch_ticker(ticker, period="1y", use_cache=use_cache)
    signals: Dict[str, Any] = {}

    earnings = run.fetch_earnings(ticker, use_cache=use_cache)
    signals["pead"] = calculate_pead_signal(pead_history(earnings), prices)

    benchmark_symbol = bundle.report.get("benchmark") or benchmark_for(ticker)
    benchmark = None
    if bundle.risk is not None and len(bundle.risk) > 2:
        benchmark = bundle.risk[2]
    if benchmark is None or getattr(benchmark, "empty", True):
        benchmark = run.fetch_ticker(benchmark_symbol, period="1y", use_cache=use_cache)
    if benchmark is not None and benchmark.empty:
        benchmark = None
    relative = calculate_relative_strength(prices, benchmark)
    if relative is not None:
        relative["benchmark"] = benchmark_symbol if benchmark is not None else None
    signals["relative_strength"] = relative

    return {k: v for k, v in signals.items() if v is not None}


def pead_history(earnings: Optional[Dict[str, pd.DataFrame]]) -> List[Dict[str, Any]]:
    """
    Earnings surprises in the shape calculate_pead_signal() expects.

    Prefers `earnings_dates` (actual announcement timestamps, so post-earnings
    drift is measured from the right day) and falls back to `earnings_history`
    (quarter-end dates).
    """
    if not earnings:
        return []

    dates = earnings.get("earnings_dates")
    rows: List[Dict[str, Any]] = []
    if dates is not None and not dates.empty:
        frame = dates.reset_index() if "Earnings Date" not in dates.columns else dates
        for record in frame.to_dict("records"):
            actual = _number(record.get("Reported EPS"))
            estimate = _number(record.get("EPS Estimate"))
            if actual is None or estimate is None or record.get("Earnings Date") is None:
                continue
            rows.append(
                {
                    "quarter": str(record["Earnings Date"]),
                    "epsActual": actual,
                    "epsEstimate": estimate,
                    "epsDifference": actual - estimate,
                    "surprisePercent": (actual - estimate) / abs(estimate) if estimate else None,
                }
            )
    if len(rows) >= 2:
        return rows

    history = earnings.get("earnings_history")
    if history is None or history.empty:
        return rows
    frame = history.reset_index() if "quarter" not in history.columns else history
    frame = frame.rename(columns={"index": "quarter"})
    return [
        {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in r.items()}
        for r in frame.to_dict("records")
    ]


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return None if pd.isna(result) else result


def _dividends_series(div_data: Optional[Dict[str, pd.DataFrame]]) -> Optional[pd.Series]:
    """Convert fetch_dividends() output into the Series ValuationAnalyzer expects."""
    if not div_data or div_data.get("dividends") is None:
        return None
    dividends_df = div_data["dividends"]
    if dividends_df.empty:
        return None
    if "Date" in dividends_df.columns:
        return dividends_df.set_index("Date")["Dividends"]
    if dividends_df.index.name == "Date":
        return dividends_df["Dividends"]
    logger.warning("Dividends DataFrame has unexpected structure")
    return dividends_df.iloc[:, 0]


def _freshness_summary(ticker: str, fetcher: DataFetcher, report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Describe how old the underlying data is, with warnings a user should see.

    Flags a stale last price bar and any resource served from an expired cache
    (which happens when a refresh fails, e.g. under rate limiting).
    """
    now = datetime.now()
    fetched_at = fetcher.freshness(ticker)
    ttl_hours = fetcher.config.cache_ttl_hours or {}
    warnings: List[str] = []

    last_price_date = None
    raw_last = ((report.get("price_data") or {}).get("latest") or {}).get("date")
    if raw_last:
        try:
            last_bar = trading_dates(pd.DatetimeIndex([pd.Timestamp(raw_last)]))[0]
            last_price_date = str(last_bar.date())
            age_days = (pd.Timestamp(now).normalize() - last_bar).days
            if age_days > STALE_PRICE_DAYS:
                warnings.append(
                    f"Latest price bar is {age_days} days old ({last_price_date}): "
                    "ticker may be halted/delisted or the refresh failed"
                )
        except ValueError, TypeError:
            pass

    for resource, stamp in sorted(fetched_at.items()):
        ttl = ttl_hours.get(resource, 0)
        if ttl <= 0:
            continue
        age_hours = (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
        if age_hours > ttl:
            warnings.append(
                f"{resource} data is {age_hours / 24:.0f} days old (refresh failed; using expired cache)"
            )

    return {
        "fetched_at": fetched_at,
        "last_price_date": last_price_date,
        "warnings": warnings,
    }
