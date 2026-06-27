"""
Multi-Ticker Comparator and Portfolio View

Provides side-by-side scoring, relative valuation, correlation analysis,
and portfolio-level statistics for multiple tickers.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..data_fetcher import DataFetcher
from ..reporting import ReportGenerator
from ..scoring import ScoringConfig, StockScorer
from ..scoring.scorer import ScoringResult

logger = logging.getLogger(__name__)


class TickerComparator:
    """
    Compare multiple tickers side-by-side with scoring, valuation, and correlation.

    Usage:
        comparator = TickerComparator(["AAPL", "MSFT", "GOOGL"])
        comparator.fetch_all()
        comparator.score_all()
        print(comparator.side_by_side_scores())
    """

    def __init__(
        self,
        tickers: List[str],
        data_fetcher: Optional[DataFetcher] = None,
        period: str = "1y",
        scoring_config: Optional[ScoringConfig] = None,
        output_dir: str = "data",
        output_format: str = "all",
    ):
        """
        Initialize TickerComparator.

        Args:
            tickers: List of ticker symbols to compare (minimum 2).
            data_fetcher: DataFetcher instance. Created if not provided.
            period: Data period for analysis (default: 1y).
            scoring_config: Scoring configuration preset. Uses defaults if not provided.
            output_dir: Directory for report output.
        """
        if len(tickers) < 2:
            raise ValueError("At least 2 tickers are required for comparison")

        self.tickers = [t.upper() for t in tickers]
        self.fetcher = data_fetcher or DataFetcher(cache_dir=output_dir)
        self.period = period
        self.scoring_config = scoring_config
        self.output_dir = output_dir
        self.output_format = output_format

        self._reports: Dict[str, Dict[str, Any]] = {}
        self._scores: Dict[str, ScoringResult] = {}

    def fetch_all(self, use_cache: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Fetch full reports for all tickers.

        Args:
            use_cache: Whether to use cached data.

        Returns:
            Dict mapping ticker -> report data.
        """
        generator = ReportGenerator(data_fetcher=self.fetcher, output_dir=self.output_dir)

        for ticker in self.tickers:
            try:
                logger.info(f"Fetching report for {ticker}...")
                report_data = generator.generate_full_report(
                    ticker=ticker,
                    period=self.period,
                    output_format=self.output_format,
                    use_cache=use_cache,
                )
                self._reports[ticker] = report_data
            except Exception as e:
                logger.error(f"Failed to fetch data for {ticker}: {e}")
                self._reports[ticker] = {"ticker": ticker, "error": str(e)}

        return self._reports

    def score_all(self) -> Dict[str, ScoringResult]:
        """
        Score all fetched tickers.

        Returns:
            Dict mapping ticker -> ScoringResult.

        Raises:
            RuntimeError: If fetch_all() has not been called.
        """
        if not self._reports:
            raise RuntimeError("No report data available. Call fetch_all() first.")

        scorer = StockScorer(config=self.scoring_config)

        for ticker, report_data in self._reports.items():
            if "error" in report_data:
                logger.warning(f"Skipping scoring for {ticker} (fetch error)")
                continue
            try:
                result = scorer.score(report_data)
                self._scores[ticker] = result
            except Exception as e:
                logger.error(f"Failed to score {ticker}: {e}")

        return self._scores

    def side_by_side_scores(self) -> pd.DataFrame:
        """
        Build a DataFrame comparing scores across tickers.

        Returns:
            DataFrame with tickers as columns and score metrics as rows.
        """
        if not self._scores:
            raise RuntimeError("No scores available. Call score_all() first.")

        rows: Dict[str, Dict[str, Any]] = {}
        for ticker, result in self._scores.items():
            rows[ticker] = {
                "Composite Score": round(result.composite_score, 1),
                "Signal": result.signal,
                "Confidence": result.confidence,
                "Technical": round(result.technical.score, 1) if result.technical else None,
                "Fundamental": round(result.fundamental.score, 1) if result.fundamental else None,
                "Risk": round(result.risk.score, 1) if result.risk else None,
                "Valuation": round(result.valuation.score, 1) if result.valuation else None,
            }

        df = pd.DataFrame(rows)
        return df

    def relative_valuation(self) -> pd.DataFrame:
        """
        Extract key valuation metrics for cross-comparison.

        Returns:
            DataFrame with tickers as columns and valuation metrics as rows.
        """
        if not self._reports:
            raise RuntimeError("No report data available. Call fetch_all() first.")

        rows: Dict[str, Dict[str, Any]] = {}
        for ticker, report in self._reports.items():
            if "error" in report:
                continue

            info = report.get("info", {})
            valuation = report.get("valuation_analysis", {})
            dcf = valuation.get("dcf_valuation", {}) if valuation else {}
            fcf_metrics = (
                report.get("fundamental_analysis", {}).get("analysis", {}).get("fcf_metrics", {})
            )

            rows[ticker] = {
                "P/E": _safe_metric(info, "pe_ratio"),
                "Forward P/E": _safe_metric(info, "forward_pe"),
                "P/B": _safe_metric(info, "price_to_book"),
                "PEG": _safe_metric(info, "peg_ratio"),
                "EV/EBITDA": _safe_metric(info, "enterprise_to_ebitda"),
                "FCF Yield %": _safe_metric(fcf_metrics, "fcf_yield"),
                "DCF Upside %": _safe_metric(dcf, "discount_premium_pct"),
            }

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df

    def correlation_matrix(self, use_cache: bool = True) -> pd.DataFrame:
        """
        Compute daily-return correlation matrix for all tickers.

        Args:
            use_cache: Whether to use cached price data.

        Returns:
            DataFrame correlation matrix (tickers × tickers).
        """
        price_frames: Dict[str, pd.Series] = {}

        for ticker in self.tickers:
            try:
                prices = self.fetcher.fetch_ticker(ticker, period=self.period, use_cache=use_cache)
                if not prices.empty and "Close" in prices.columns:
                    price_frames[ticker] = prices["Close"]
            except Exception as e:
                logger.warning(f"Could not fetch prices for {ticker}: {e}")

        if len(price_frames) < 2:
            logger.warning("Need at least 2 tickers with price data for correlation")
            return pd.DataFrame()

        combined = pd.DataFrame(price_frames)
        returns = combined.pct_change().dropna()
        return returns.corr()

    def key_metrics_table(self) -> pd.DataFrame:
        """
        Pull key summary metrics for all tickers.

        Returns:
            DataFrame with tickers as columns and metric names as rows.
        """
        if not self._reports:
            raise RuntimeError("No report data available. Call fetch_all() first.")

        rows: Dict[str, Dict[str, Any]] = {}
        for ticker, report in self._reports.items():
            if "error" in report:
                continue

            info = report.get("info", {})
            revenue_growth = (
                report.get("fundamental_analysis", {})
                .get("analysis", {})
                .get("growth_rates", {})
                .get("revenue", {})
            )
            rows[ticker] = {
                "Market Cap": _format_large_number(info.get("market_cap")),
                "Revenue Growth %": _safe_metric(revenue_growth, "1y"),
                "ROE %": _safe_metric(info, "roe", multiply=100),
                "Dividend Yield %": _safe_metric(info, "dividend_yield"),
                "Beta": _safe_metric(info, "beta"),
                "52w High": _safe_metric(info, "52w_high"),
                "52w Low": _safe_metric(info, "52w_low"),
            }

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows)


@dataclass
class PortfolioView:
    """
    Portfolio-level view for a collection of tickers with optional weights.

    Usage:
        pv = PortfolioView(["AAPL", "MSFT", "GOOGL"], weights=[0.5, 0.3, 0.2])
        stats = pv.portfolio_stats(comparator)
    """

    tickers: List[str]
    weights: List[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.weights:
            n = len(self.tickers)
            self.weights = [1.0 / n] * n

        if len(self.weights) != len(self.tickers):
            raise ValueError(
                f"Number of weights ({len(self.weights)}) must match "
                f"number of tickers ({len(self.tickers)})"
            )

        total = sum(self.weights)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.3f}")

    def portfolio_stats(self, comparator: TickerComparator) -> Dict[str, Any]:
        """
        Compute portfolio-level statistics.

        Args:
            comparator: A TickerComparator that has already called fetch_all() and score_all().

        Returns:
            Dict with portfolio statistics.
        """
        scores = comparator._scores
        reports = comparator._reports

        # Weighted composite score
        weighted_score = 0.0
        score_available = 0
        for ticker, weight in zip(self.tickers, self.weights):
            if ticker in scores:
                weighted_score += scores[ticker].composite_score * weight
                score_available += 1

        # Weighted beta
        weighted_beta = 0.0
        beta_available = 0
        for ticker, weight in zip(self.tickers, self.weights):
            if ticker in reports and "error" not in reports[ticker]:
                info = reports[ticker].get("info", {})
                beta = info.get("beta")
                if beta is not None:
                    weighted_beta += float(beta) * weight
                    beta_available += 1

        # Diversification ratio from correlation matrix
        try:
            corr = comparator.correlation_matrix()
            diversification = self._diversification_ratio(corr)
        except Exception:
            diversification = None

        result: Dict[str, Any] = {
            "tickers": self.tickers,
            "weights": self.weights,
            "weighted_composite_score": round(weighted_score, 1) if score_available else None,
            "weighted_beta": round(weighted_beta, 2) if beta_available else None,
            "diversification_ratio": round(diversification, 3) if diversification else None,
            "holdings": [],
        }

        for ticker, weight in zip(self.tickers, self.weights):
            holding: Dict[str, Any] = {
                "ticker": ticker,
                "weight": weight,
            }
            if ticker in scores:
                holding["score"] = round(scores[ticker].composite_score, 1)
                holding["signal"] = scores[ticker].signal
            result["holdings"].append(holding)

        return result

    def _diversification_ratio(self, corr_matrix: pd.DataFrame) -> Optional[float]:
        """
        Compute diversification ratio.

        DR = (weighted avg of individual vols) / (portfolio vol)
        Higher = more diversified. DR=1 means perfect correlation.
        """
        if corr_matrix.empty:
            return None

        available = [t for t in self.tickers if t in corr_matrix.columns]
        if len(available) < 2:
            return None

        # Use correlation as proxy (assume equal vol for simplicity)
        w = np.array([self.weights[self.tickers.index(t)] for t in available])
        corr = corr_matrix.loc[available, available].values

        # Portfolio variance (assuming unit individual variances)
        port_var = float(w @ corr @ w)
        if port_var <= 0:
            return None

        # Weighted average individual vol = sum(w_i * 1) = 1 (unit vols)
        weighted_avg_vol = float(np.sum(w))

        return weighted_avg_vol / np.sqrt(port_var)


# ==================== Risk Parity & Portfolio Construction ====================


def calculate_risk_parity_weights(
    price_data_map: Dict[str, pd.DataFrame],
) -> Optional[Dict[str, Any]]:
    """
    Calculate inverse-volatility (risk parity) portfolio weights.

    Risk parity weights each position inversely proportional to its volatility,
    so each position contributes roughly equal risk to the portfolio.
    This produces more stable portfolios than equal-weight without requiring
    full covariance matrix optimization.

    Formula: w_i = (1/σ_i) / Σ(1/σ_j)

    Args:
        price_data_map: Dict mapping ticker -> DataFrame with 'Close' prices

    Returns:
        Dictionary with risk parity weights and supporting metrics, or None
    """
    if len(price_data_map) < 2:
        return None

    volatilities: Dict[str, float] = {}

    for ticker, price_data in price_data_map.items():
        if price_data is None or price_data.empty or "Close" not in price_data.columns:
            continue
        daily_returns = price_data["Close"].pct_change().dropna()
        if len(daily_returns) < 20:
            continue
        ann_vol = float(daily_returns.std()) * np.sqrt(252)
        if ann_vol > 0:
            volatilities[ticker] = ann_vol

    if len(volatilities) < 2:
        return None

    # Inverse-volatility weights
    inv_vols = {t: 1.0 / v for t, v in volatilities.items()}
    total_inv_vol = sum(inv_vols.values())
    weights = {t: iv / total_inv_vol for t, iv in inv_vols.items()}

    # Equal-weight comparison
    n = len(weights)
    equal_weight = 1.0 / n

    return {
        "weights": weights,
        "volatilities": volatilities,
        "method": "inverse_volatility",
        "description": "Weights each position inversely to its volatility (lower vol = higher weight)",
        "comparison_vs_equal_weight": {
            ticker: {
                "risk_parity": round(w, 4),
                "equal_weight": round(equal_weight, 4),
                "difference": round(w - equal_weight, 4),
            }
            for ticker, w in weights.items()
        },
    }


def identify_correlation_flags(
    correlation_matrix: pd.DataFrame,
    high_threshold: float = 0.80,
    hedge_threshold: float = -0.30,
) -> Dict[str, Any]:
    """
    Identify portfolio diversification issues from a correlation matrix.

    Flags:
    - Highly correlated pairs (>0.80): redundant positions
    - Negatively correlated pairs (<-0.30): potential hedging opportunities
    - Overall diversification score

    Args:
        correlation_matrix: Ticker-by-ticker correlation DataFrame
        high_threshold: Correlation above this is flagged as redundant
        hedge_threshold: Correlation below this is flagged as hedge opportunity

    Returns:
        Dictionary with correlation flags and diversification assessment
    """
    if correlation_matrix.empty or len(correlation_matrix) < 2:
        return {}

    tickers = list(correlation_matrix.columns)
    n = len(tickers)

    redundant_pairs = []
    hedge_pairs = []
    all_correlations = []

    for i in range(n):
        for j in range(i + 1, n):
            corr = float(correlation_matrix.iloc[i, j])
            all_correlations.append(corr)
            pair = (tickers[i], tickers[j])

            if corr >= high_threshold:
                redundant_pairs.append(
                    {
                        "pair": pair,
                        "correlation": round(corr, 3),
                        "warning": f"{pair[0]} and {pair[1]} move together — consider reducing one",
                    }
                )
            elif corr <= hedge_threshold:
                hedge_pairs.append(
                    {
                        "pair": pair,
                        "correlation": round(corr, 3),
                        "opportunity": f"{pair[0]} and {pair[1]} offset each other — good for hedging",
                    }
                )

    # Diversification score: lower average correlation = better diversification
    avg_corr = float(np.mean(all_correlations)) if all_correlations else 0.0
    # Scale: avg_corr 0 = perfect (100), avg_corr 1 = worst (0)
    diversification_score = max(0, min(100, int((1 - avg_corr) * 100)))

    return {
        "diversification_score": diversification_score,
        "average_correlation": round(avg_corr, 3),
        "redundant_pairs": redundant_pairs,
        "hedge_opportunities": hedge_pairs,
        "total_pairs_analyzed": len(all_correlations),
        "assessment": (
            "Well diversified"
            if diversification_score >= 70
            else "Moderately diversified"
            if diversification_score >= 40
            else "Poorly diversified — high correlation between holdings"
        ),
    }


def _safe_metric(
    data: Dict[str, Any],
    key: str,
    multiply: float = 1.0,
    divisor_key: Optional[str] = None,
    source: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Safely extract a numeric metric from a dict."""
    val = data.get(key)
    if val is None:
        return None
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None

    if divisor_key:
        src = source or data
        divisor = src.get(divisor_key)
        if divisor is None or divisor == 0:
            return None
        val = val / float(divisor)

    return round(val * multiply, 2) if multiply != 1.0 else round(val, 2)


def _format_large_number(value: Any) -> Optional[str]:
    """Format large numbers with B/M/K suffixes."""
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None

    if abs(val) >= 1e12:
        return f"{val / 1e12:.1f}T"
    elif abs(val) >= 1e9:
        return f"{val / 1e9:.1f}B"
    elif abs(val) >= 1e6:
        return f"{val / 1e6:.1f}M"
    elif abs(val) >= 1e3:
        return f"{val / 1e3:.1f}K"
    return f"{val:.0f}"
