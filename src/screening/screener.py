"""
Two-stage stock screener

Stage 1 (cheap, whole universe): company info + one year of prices per ticker,
apply filters, then rank cross-sectionally with the multi-factor model
(value, quality, momentum, low volatility).

Stage 2 (expensive, top N only): the full analysis pipeline and composite
score for the best factor-ranked candidates. Stage-1 data lands in the cache,
so stage 2 reuses it instead of downloading prices again.
"""

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ..data_fetcher import DataFetcher
from ..discovery.factor_ranking import FactorRanker, FactorScore, FactorWeights
from ..pipeline import AnalysisOptions, analyze_ticker
from ..scoring.scorer import ScoringResult
from ..utils.concurrency import DEFAULT_WORKERS, run_concurrently
from ..utils.toon_serializer import report_to_toon

logger = logging.getLogger(__name__)

# Stage-1 price window. Matches the pipeline's technical/fundamental period so the
# cached file is reused in stage 2. Gives an ~11-minus-1-month momentum window.
STAGE1_PERIOD = "1y"

ProgressFn = Callable[[str, int, int], None]


@dataclass(frozen=True)
class ScreenFilters:
    """
    Universe filters applied to company info before ranking.

    Market cap and volume are in the listing's own currency/shares, so mixing
    exchanges (e.g. sp500 + obx) makes cap thresholds approximate.
    """

    sectors: Tuple[str, ...] = ()
    exclude_sectors: Tuple[str, ...] = ()
    min_market_cap: Optional[float] = None
    max_market_cap: Optional[float] = None
    min_avg_volume: Optional[float] = None

    @property
    def active(self) -> bool:
        return bool(
            self.sectors
            or self.exclude_sectors
            or self.min_market_cap is not None
            or self.max_market_cap is not None
            or self.min_avg_volume is not None
        )

    def rejection_reason(self, info: Dict[str, Any]) -> Optional[str]:
        """Why a ticker fails the filters, or None if it passes."""
        if not self.active:
            return None
        if not info:
            return "no company info to filter on"

        sector_text = f"{info.get('sector') or ''} / {info.get('industry') or ''}".lower()
        if self.sectors and not any(s.lower() in sector_text for s in self.sectors):
            return f"sector {info.get('sector') or 'unknown'}"
        if any(s.lower() in sector_text for s in self.exclude_sectors):
            return f"excluded sector {info.get('sector')}"

        market_cap = info.get("market_cap")
        if self.min_market_cap is not None and (market_cap or 0) < self.min_market_cap:
            return f"market cap {format_amount(market_cap)} below minimum"
        if self.max_market_cap is not None and market_cap and market_cap > self.max_market_cap:
            return f"market cap {format_amount(market_cap)} above maximum"

        volume = info.get("avg_volume")
        if self.min_avg_volume is not None and (volume or 0) < self.min_avg_volume:
            return f"avg volume {format_amount(volume)} below minimum"
        return None


@dataclass
class ScreenCandidate:
    """One ticker's journey through the screen."""

    ticker: str
    info: Dict[str, Any] = field(default_factory=dict)
    factor: Optional[FactorScore] = None
    factor_rank: Optional[int] = None
    scoring: Optional[ScoringResult] = None
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def name(self) -> str:
        name = self.info.get("name")
        return name if name and name != "N/A" else self.ticker

    @property
    def sector(self) -> str:
        sector = self.info.get("sector")
        return sector if sector and sector != "N/A" else ""

    def to_row(self) -> Dict[str, Any]:
        """Flat record for CSV/JSON export."""
        s, f = self.scoring, self.factor

        def _dim(name: str) -> Optional[float]:
            dim = getattr(s, name, None) if s else None
            return round(dim.score, 1) if dim else None

        def _pct(value: Optional[float]) -> Optional[float]:
            return round(value, 1) if value is not None else None

        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "industry": self.info.get("industry"),
            "currency": self.info.get("currency"),
            "market_cap": self.info.get("market_cap"),
            "factor_rank": self.factor_rank,
            "factor_composite": _pct(f.composite_score) if f else None,
            "factor_value": _pct(f.value_score) if f else None,
            "factor_quality": _pct(f.quality_score) if f else None,
            "factor_momentum": _pct(f.momentum_score) if f else None,
            "factor_low_vol": _pct(f.low_vol_score) if f else None,
            "score": round(s.composite_score, 1) if s else None,
            "signal": s.signal if s else None,
            "confidence": s.confidence if s else None,
            "technical": _dim("technical"),
            "fundamental": _dim("fundamental"),
            "risk": _dim("risk"),
            "valuation": _dim("valuation"),
            "warnings": "; ".join(self.warnings) or None,
            "error": self.error,
        }


@dataclass
class ScreenResult:
    universe: str
    preset: str
    universe_size: int
    scored: List[ScreenCandidate]  # stage-2 candidates, best composite score first
    ranked: List[ScreenCandidate]  # every stage-1 survivor, in factor order
    excluded: Dict[str, str]  # ticker -> reason (filtered out or data unavailable)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "meta": {
                "universe": self.universe,
                "preset": self.preset,
                "generated_at": self.generated_at,
                "universe_size": self.universe_size,
                "ranked": len(self.ranked),
                "scored": len(self.scored),
                "excluded": len(self.excluded),
            },
            "results": [c.to_row() for c in self.scored],
            "factor_ranking": [c.to_row() for c in self.ranked],
            "excluded": self.excluded,
        }


class Screener:
    """Runs the two-stage screen over a list of tickers."""

    def __init__(
        self,
        fetcher: Optional[DataFetcher] = None,
        options: Optional[AnalysisOptions] = None,
        workers: int = DEFAULT_WORKERS,
        factor_weights: Optional[FactorWeights] = None,
    ):
        self.fetcher = fetcher or DataFetcher()
        # Holders/ratings/news aren't used by scoring; skip them for speed
        self.options = replace(options or AnalysisOptions(), include_context=False)
        self.workers = workers
        self.ranker = FactorRanker(weights=factor_weights)

    def run(
        self,
        tickers: Sequence[str],
        filters: Optional[ScreenFilters] = None,
        top_n: int = 20,
        universe_label: str = "custom",
        progress: Optional[ProgressFn] = None,
    ) -> ScreenResult:
        filters = filters or ScreenFilters()
        tickers = list(dict.fromkeys(t.upper() for t in tickers))
        excluded: Dict[str, str] = {}

        # ---- Stage 1: info + prices for everyone ----
        stage1: Dict[str, Tuple[Dict[str, Any], pd.DataFrame]] = {}
        for i, (ticker, data, error) in enumerate(
            run_concurrently(self._fetch_stage1, tickers, workers=self.workers), 1
        ):
            if progress:
                progress("rank", i, len(tickers))
            if error is not None or data is None:
                excluded[ticker] = f"data unavailable: {error}"
                continue
            info, prices = data
            reason = filters.rejection_reason(info)
            if reason:
                excluded[ticker] = f"filtered: {reason}"
                continue
            stage1[ticker] = (info, prices)

        candidates = {t: ScreenCandidate(ticker=t, info=info) for t, (info, _) in stage1.items()}

        # Factor ranking needs a cross-section; a lone survivor goes straight to scoring
        factor_scores = self.ranker.rank_universe(
            {t: {"info": info, "price_data": prices} for t, (info, prices) in stage1.items()}
        )
        for rank, factor in enumerate(factor_scores, 1):
            candidates[factor.ticker].factor = factor
            candidates[factor.ticker].factor_rank = rank
        ranked = sorted(
            candidates.values(),
            key=lambda c: c.factor_rank if c.factor_rank is not None else float("inf"),
        )

        # ---- Stage 2: full analysis for the top N ----
        shortlist = ranked[:top_n]
        for i, (candidate, bundle, error) in enumerate(
            run_concurrently(self._analyze, shortlist, workers=self.workers), 1
        ):
            if progress:
                progress("score", i, len(shortlist))
            if error is not None or bundle is None:
                candidate.error = str(error)
                continue
            candidate.scoring = bundle.scoring
            candidate.warnings = bundle.freshness_warnings
            if bundle.scoring is None:
                candidate.error = bundle.errors.get("scoring", "scoring failed")

        scored = sorted(
            shortlist,
            key=lambda c: (c.scoring is None, -(c.scoring.composite_score if c.scoring else 0)),
        )
        preset = self.options.scoring_config.name if self.options.scoring_config else "default"
        return ScreenResult(
            universe=universe_label,
            preset=preset,
            universe_size=len(tickers),
            scored=scored,
            ranked=ranked,
            excluded=excluded,
        )

    def _fetch_stage1(self, ticker: str) -> Tuple[Dict[str, Any], pd.DataFrame]:
        use_cache = self.options.use_cache
        prices = self.fetcher.fetch_ticker(ticker, period=STAGE1_PERIOD, use_cache=use_cache)
        info = self.fetcher.get_ticker_info(ticker, use_cache=use_cache)
        return info, prices

    def _analyze(self, candidate: ScreenCandidate):
        return analyze_ticker(candidate.ticker, self.fetcher, self.options)


# ==================== Output ====================


def format_screen_table(result: ScreenResult) -> str:
    """Console table of scored candidates."""
    lines = [
        "=" * 100,
        f"  SCREEN: {result.universe}  |  preset: {result.preset}  |  "
        f"{result.universe_size} tickers -> {len(result.ranked)} ranked -> "
        f"{len(result.scored)} scored",
        "=" * 100,
        "",
        f"  {'#':>3} {'Ticker':<10} {'Name':<22} {'Sector':<18} {'Score':>5}  {'Signal':<11} "
        f"{'Conf':<6} {'FRank':>5}  {'Val':>3} {'Qua':>3} {'Mom':>3} {'LVo':>3}",
        "  " + "-" * 98,
    ]

    def _pct(value: Optional[float]) -> str:
        return f"{value:.0f}" if value is not None else "-"

    for i, c in enumerate(result.scored, 1):
        f = c.factor
        if c.scoring:
            score_cols = (
                f"{c.scoring.composite_score:>5.0f}  {c.scoring.signal:<11} "
                f"{c.scoring.confidence:<6}"
            )
        else:
            score_cols = f"{'ERR':>5}  {'':<11} {'':<6}"
        lines.append(
            f"  {i:>3} {c.ticker:<10} {c.name[:21]:<22} {c.sector[:17]:<18} {score_cols} "
            f"{_pct(c.factor_rank):>5}  "
            f"{_pct(f.value_score if f else None):>3} {_pct(f.quality_score if f else None):>3} "
            f"{_pct(f.momentum_score if f else None):>3} {_pct(f.low_vol_score if f else None):>3}"
        )
        if c.error:
            lines.append(f"        └─ error: {c.error[:80]}")
        for warning in c.warnings:
            lines.append(f"        └─ ! {warning[:90]}")

    lines += [
        "",
        "  Score = composite 0-100 (technical/fundamental/risk/valuation).",
        "  FRank = factor rank in the universe; Val/Qua/Mom/LVo = factor percentiles (100 = best).",
    ]
    return "\n".join(lines)


def save_screen(result: ScreenResult, output_dir: str, output_format: str = "all") -> List[Path]:
    """
    Write screen results to <output_dir>/_screens/.

    CSV is always written (spreadsheet-friendly); JSON for json/all, TOON for toon/all.
    A `latest.*` copy is kept alongside the timestamped file.
    """
    screens_dir = Path(output_dir) / "_screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe_label = re.sub(r"[^A-Za-z0-9_+-]+", "_", result.universe)[:60]
    base = f"screen_{safe_label}_{stamp}"
    data = result.to_dict()
    written: List[Path] = []

    def _write(suffix: str, content: str):
        for name in (f"{base}.{suffix}", f"latest.{suffix}"):
            path = screens_dir / name
            path.write_text(content, encoding="utf-8")
        written.append(screens_dir / f"{base}.{suffix}")

    _write("csv", pd.DataFrame(data["results"]).to_csv(index=False))
    if output_format in ("json", "all"):
        _write("json", json.dumps(data, indent=2, default=str))
    if output_format in ("toon", "all"):
        _write("toon", report_to_toon(data))
    return written


_AMOUNT = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kKmMbBtT]?)\s*$")
_MULTIPLIERS = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def parse_amount(text: str) -> float:
    """Parse '10B', '500m', '2.5T', '750000' into a number."""
    match = _AMOUNT.match(text)
    if not match:
        raise ValueError(f"Can't parse amount '{text}' (examples: 500M, 10B, 1.5T)")
    number, unit = match.groups()
    return float(number) * _MULTIPLIERS[unit.lower()]


def format_amount(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= size:
            return f"{value / size:.1f}{unit}"
    return f"{value:.0f}"
