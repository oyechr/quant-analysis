"""Multi-ticker comparison and portfolio view"""

from .comparator import (
    PortfolioView,
    TickerComparator,
    calculate_risk_parity_weights,
    identify_correlation_flags,
    return_correlations,
)
from .formatters import (
    format_comparison_json,
    format_comparison_markdown,
    format_comparison_table,
    format_correlation_heatmap,
    format_diversification,
    format_portfolio_view,
)

__all__ = [
    "TickerComparator",
    "PortfolioView",
    "calculate_risk_parity_weights",
    "identify_correlation_flags",
    "return_correlations",
    "format_comparison_table",
    "format_comparison_markdown",
    "format_comparison_json",
    "format_correlation_heatmap",
    "format_diversification",
    "format_portfolio_view",
]
