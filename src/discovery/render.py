"""Terminal rendering of a DiscoveryResult (`quant discover`)."""

from typing import List

from .models import DiscoveryResult

_RULE = "  " + "=" * 66


def _heading(title: str) -> List[str]:
    return [_RULE, f"  {title}", _RULE, ""]


def render_text(result: DiscoveryResult, top: int = 20) -> str:
    """Overlap, sector clusters, convergence and contrarian sections, `top` rows each."""
    lines = [
        "",
        f"  Analyzed {result.portfolios_analyzed} portfolios, "
        f"{result.total_holdings} total holdings",
        "",
    ]

    if result.overlap_signals:
        lines += _heading("TICKER OVERLAP (consensus picks)")
        lines.append(f"  {'Ticker':<10} {'Name':<25} {'Overlap':>8} {'Strength':>9} {'Sector':<20}")
        lines.append("  " + "-" * 74)
        for signal in result.overlap_signals[:top]:
            name = (signal.name or "")[:24]
            sector_str = (signal.sector or "N/A")[:19]
            lines.append(
                f"  {signal.ticker:<10} {name:<25} "
                f"{signal.overlap_count:>3}/{signal.total_portfolios:<4} "
                f"{signal.strength:>6.1f}   {sector_str:<20}"
            )
            if signal.portfolios:
                portfolios_str = ", ".join(signal.portfolios[:4])
                if len(signal.portfolios) > 4:
                    portfolios_str += f" +{len(signal.portfolios) - 4} more"
                lines.append(f"             └─ {portfolios_str}")
            if signal.recent_actions:
                actions_str = ", ".join(signal.recent_actions[:4])
                lines.append(f"             └─ Actions: {actions_str}")
        lines.append("")

    if result.sector_clusters:
        lines += _heading("SECTOR/INDUSTRY CLUSTERS")
        lines.append(
            f"  {'Sector > Industry':<40} {'Holdings':>9} {'Portfolios':>11} {'Strength':>9}"
        )
        lines.append("  " + "-" * 71)
        for cluster in result.sector_clusters[:top]:
            label = cluster.label[:39]
            lines.append(
                f"  {label:<40} {cluster.holding_count:>6}    "
                f"{len(cluster.portfolios):>5}      {cluster.strength:>6.1f}"
            )
            if cluster.tickers:
                tickers_str = ", ".join(cluster.tickers[:6])
                if len(cluster.tickers) > 6:
                    tickers_str += f" +{len(cluster.tickers) - 6} more"
                lines.append(f"    └─ {tickers_str}")
        lines.append("")

    if result.convergence_events:
        lines += _heading("ACTIVITY CONVERGENCE")
        for event in result.convergence_events[:top]:
            name = event.name or event.ticker
            lines.append(
                f"  {event.ticker:<8} {name:<20} "
                f"Action: {event.action.upper():<5} "
                f"Window: {event.window_days}d  "
                f"Strength: {event.strength:.1f}"
            )
            lines.append(f"    └─ Portfolios: {', '.join(event.portfolios)}")
        lines.append("")

    if result.contrarian_signals:
        lines += _heading("CONTRARIAN SIGNALS (disagreement)")
        for contrarian in result.contrarian_signals[:top]:
            name = contrarian.name or contrarian.ticker
            lines.append(
                f"  {contrarian.ticker:<8} {name:<20} "
                f"Net: {contrarian.net_direction.upper():<8} "
                f"Strength: {contrarian.strength:.1f}"
            )
            lines.append(f"    └─ Buyers:  {', '.join(contrarian.buyers)}")
            lines.append(f"    └─ Sellers: {', '.join(contrarian.sellers)}")
        lines.append("")

    return "\n".join(lines)
