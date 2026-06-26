"""
Data models for the Portfolio Discovery module.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Holding:
    """A single holding within a tracked portfolio."""

    ticker: str
    name: str
    shares: Optional[float] = None
    value: Optional[float] = None  # Market value in USD
    sector: Optional[str] = None
    industry: Optional[str] = None
    weight: Optional[float] = None  # % of portfolio
    action: Optional[str] = None  # "buy", "sell", "hold", "new", "exit"
    date: Optional[datetime] = None

    def __post_init__(self):
        self.ticker = self.ticker.upper().strip()


@dataclass
class TrackedPortfolio:
    """A notable portfolio being tracked (e.g., a 13F filer, congress member)."""

    name: str
    source: str  # "edgar_13f", "congress", "manual", etc.
    holdings: list[Holding] = field(default_factory=list)
    cik: Optional[str] = None  # SEC CIK number (for EDGAR source)
    filing_date: Optional[datetime] = None
    period_of_report: Optional[datetime] = None
    description: Optional[str] = None

    @property
    def tickers(self) -> set[str]:
        """Get all unique tickers in this portfolio."""
        return {h.ticker for h in self.holdings}

    @property
    def total_value(self) -> Optional[float]:
        """Total portfolio value (sum of all holding values)."""
        values = [h.value for h in self.holdings if h.value is not None]
        return sum(values) if values else None


@dataclass
class DiscoverySignal:
    """A signal generated from cross-portfolio analysis."""

    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    signal_type: str = "overlap"  # "overlap", "convergence", "contrarian", "sector_cluster"
    strength: float = 0.0  # 0-100 signal strength
    portfolios: list[str] = field(default_factory=list)  # portfolio names that hold it
    overlap_count: int = 0
    total_portfolios: int = 0
    recent_actions: list[str] = field(default_factory=list)  # e.g. "Berkshire: BUY 2024-Q4"
    notes: list[str] = field(default_factory=list)

    @property
    def overlap_pct(self) -> float:
        """Percentage of tracked portfolios holding this ticker."""
        if self.total_portfolios == 0:
            return 0.0
        return (self.overlap_count / self.total_portfolios) * 100


@dataclass
class SectorCluster:
    """A cluster of holdings in a specific sector/industry across portfolios."""

    sector: str
    industry: Optional[str] = None
    tickers: list[str] = field(default_factory=list)
    portfolios: list[str] = field(default_factory=list)
    total_value: Optional[float] = None
    weight_avg: Optional[float] = None  # Average weight across portfolios
    holding_count: int = 0
    strength: float = 0.0  # 0-100, how concentrated this cluster is

    @property
    def label(self) -> str:
        """Human-readable label for this cluster."""
        if self.industry:
            return f"{self.sector} > {self.industry}"
        return self.sector


@dataclass
class ConvergenceEvent:
    """Multiple portfolios taking the same action on the same ticker within a time window."""

    ticker: str
    name: Optional[str] = None
    action: str = "buy"  # "buy" or "sell"
    portfolios: list[str] = field(default_factory=list)
    dates: list[datetime] = field(default_factory=list)
    window_days: int = 90  # Time window in which the actions occurred
    strength: float = 0.0


@dataclass
class ContrarianSignal:
    """Signal where one set of portfolios is buying while another is selling."""

    ticker: str
    name: Optional[str] = None
    buyers: list[str] = field(default_factory=list)
    sellers: list[str] = field(default_factory=list)
    net_direction: str = "bullish"  # "bullish" if more buyers, "bearish" if more sellers
    strength: float = 0.0


@dataclass
class DiscoveryResult:
    """Complete result from a discovery analysis run."""

    portfolios_analyzed: int = 0
    total_holdings: int = 0
    overlap_signals: list[DiscoverySignal] = field(default_factory=list)
    sector_clusters: list[SectorCluster] = field(default_factory=list)
    convergence_events: list[ConvergenceEvent] = field(default_factory=list)
    contrarian_signals: list[ContrarianSignal] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def top_signals(self) -> list[DiscoverySignal]:
        """Get top overlap signals sorted by strength."""
        return sorted(self.overlap_signals, key=lambda s: s.strength, reverse=True)

    def to_dict(self) -> dict:
        """Serialize to dict for JSON/TOON output."""
        return {
            "meta": {
                "portfolios_analyzed": self.portfolios_analyzed,
                "total_holdings": self.total_holdings,
                "generated_at": self.generated_at.isoformat(),
            },
            "overlap_signals": [
                {
                    "ticker": s.ticker,
                    "name": s.name,
                    "sector": s.sector,
                    "industry": s.industry,
                    "strength": round(s.strength, 1),
                    "overlap_count": s.overlap_count,
                    "overlap_pct": round(s.overlap_pct, 1),
                    "portfolios": s.portfolios,
                    "recent_actions": s.recent_actions,
                }
                for s in self.top_signals
            ],
            "sector_clusters": [
                {
                    "sector": c.sector,
                    "industry": c.industry,
                    "label": c.label,
                    "tickers": c.tickers,
                    "portfolios": c.portfolios,
                    "holding_count": c.holding_count,
                    "strength": round(c.strength, 1),
                }
                for c in sorted(self.sector_clusters, key=lambda c: c.strength, reverse=True)
            ],
            "convergence_events": [
                {
                    "ticker": e.ticker,
                    "name": e.name,
                    "action": e.action,
                    "portfolios": e.portfolios,
                    "window_days": e.window_days,
                    "strength": round(e.strength, 1),
                }
                for e in sorted(self.convergence_events, key=lambda e: e.strength, reverse=True)
            ],
            "contrarian_signals": [
                {
                    "ticker": s.ticker,
                    "name": s.name,
                    "buyers": s.buyers,
                    "sellers": s.sellers,
                    "net_direction": s.net_direction,
                    "strength": round(s.strength, 1),
                }
                for s in sorted(self.contrarian_signals, key=lambda s: s.strength, reverse=True)
            ],
        }
