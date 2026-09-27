"""
Red Flags

Rule-based checks over a report dict (the shape `analyze_ticker` produces)
for problems that should make you stop and look closer before buying:
possible earnings manipulation, distress, cash burn, dilution, an uncovered
dividend, thin interest cover, stale statements, and low-confidence data.

Each rule is a small function that returns zero or more RedFlags, so rules can
be tested one at a time with synthetic reports.
"""

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

BENEISH_THRESHOLD = -1.78  # above = likely manipulator (Beneish 1999)
BENEISH_MIN_COMPONENTS = 5  # fewer inputs and the score is mostly defaults
ALTMAN_DISTRESS = 1.81
DILUTION_PCT_PER_YEAR = 3.0
HEAVY_DILUTION_PCT_PER_YEAR = 10.0
INTEREST_COVERAGE_MIN = 2.0
STATEMENT_MAX_AGE_MONTHS = 15
DATA_COVERAGE_MIN = 0.60

# Altman Z and interest cover are built for industrial companies; for banks
# and insurers leverage and interest are the business model.
_FINANCIAL_SECTORS = ("financial services", "financial")


@dataclass
class RedFlag:
    severity: str  # "high", "medium", or "low"
    title: str
    detail: str
    rule: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def find_red_flags(report: Dict[str, Any], today: Optional[datetime] = None) -> List[RedFlag]:
    """Run every rule against a report dict; most severe first."""
    today = today or _report_date(report)
    flags: List[RedFlag] = []
    for rule in RULES:
        flags.extend(rule(report, today))
    return sorted(flags, key=lambda f: SEVERITY_ORDER.get(f.severity, 99))


# ==================== Rules ====================


def check_beneish(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    beneish = _quality(report).get("beneish_m") or {}
    m_score = _num(beneish.get("m_score"))
    if m_score is None or m_score <= BENEISH_THRESHOLD:
        return []
    components = beneish.get("components_available")
    partial = components is not None and components < BENEISH_MIN_COMPONENTS
    detail = f"M-Score {m_score:.2f} is above {BENEISH_THRESHOLD} (possible earnings manipulation)"
    if partial:
        detail += f"; only {components}/8 inputs available, so treat as a weak signal"
    return [
        RedFlag(
            severity="medium" if partial else "high",
            title="Beneish M-Score flags possible manipulation",
            detail=detail,
            rule="beneish",
        )
    ]


def check_altman(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    z = _num(_quality(report).get("altman_z"))
    if z is None or z >= ALTMAN_DISTRESS or _is_financial(report):
        return []
    return [
        RedFlag(
            severity="high",
            title="Altman Z-Score in distress zone",
            detail=f"Z = {z:.2f} (below {ALTMAN_DISTRESS}: elevated bankruptcy risk)",
            rule="altman",
        )
    ]


def check_negative_fcf(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    fcf = [v for v in _history(report).get("free_cash_flow", [])[:3] if v is not None]
    if len(fcf) < 2:
        return []
    negative = sum(1 for v in fcf if v < 0)
    if negative < 2:
        return []
    return [
        RedFlag(
            severity="high" if negative == len(fcf) else "medium",
            title="Negative free cash flow",
            detail=f"FCF negative in {negative} of the last {len(fcf)} years",
            rule="negative_fcf",
        )
    ]


def check_dilution(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    history = _history(report)
    rate = share_growth_per_year(history.get("shares_outstanding", []), history.get("periods", []))
    if rate is None or rate <= DILUTION_PCT_PER_YEAR:
        return []
    return [
        RedFlag(
            severity="high" if rate > HEAVY_DILUTION_PCT_PER_YEAR else "medium",
            title="Share count dilution",
            detail=f"Shares outstanding growing {rate:.1f}%/yr (threshold {DILUTION_PCT_PER_YEAR:.0f}%)",
            rule="dilution",
        )
    ]


def check_dividend_coverage(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    info = report.get("info") or {}
    dividend = (report.get("valuation_analysis") or {}).get("dividend_analysis") or {}
    pays = dividend.get("pays_dividends") or (_num(info.get("dividend_yield")) or 0) > 0
    if not pays:
        return []

    problems = []
    payout = _num(info.get("payout_ratio"))  # Yahoo: decimal (1.2 = 120%)
    payout_pct = _num(dividend.get("payout_ratio"))  # valuation: percent
    if payout is None and payout_pct is not None:
        payout = payout_pct / 100
    if payout is not None and payout > 1.0:
        problems.append(f"payout ratio {payout:.0%} of earnings")

    history = _history(report)
    fcf = _first(history.get("free_cash_flow", []))
    paid = _first(history.get("dividends_paid", []))
    if fcf is not None and paid:
        coverage = fcf / abs(paid)
        if coverage < 1.0:
            problems.append(f"FCF covers the dividend {coverage:.2f}x")

    if not problems:
        return []
    return [
        RedFlag(
            severity="medium",
            title="Dividend not covered",
            detail="; ".join(problems),
            rule="dividend_coverage",
        )
    ]


def check_interest_coverage(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    if _is_financial(report):
        return []
    coverage = _first(_history(report).get("interest_coverage", []))
    if coverage is None or coverage >= INTEREST_COVERAGE_MIN:
        return []
    return [
        RedFlag(
            severity="high" if coverage < 1.0 else "medium",
            title="Weak interest coverage",
            detail=f"EBIT covers interest {coverage:.1f}x (below {INTEREST_COVERAGE_MIN:.0f}x)",
            rule="interest_coverage",
        )
    ]


def check_statement_age(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    periods = _history(report).get("periods") or []
    if not periods:
        return []
    try:
        latest = datetime.fromisoformat(str(periods[0])[:10])
    except ValueError:
        return []
    months = (today - latest).days / 30.44
    if months <= STATEMENT_MAX_AGE_MONTHS:
        return []
    return [
        RedFlag(
            severity="medium",
            title="Stale annual statements",
            detail=f"Latest annual statements are for {latest.date()} ({months:.0f} months old)",
            rule="statement_age",
        )
    ]


def check_confidence(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    scoring = report.get("scoring") or {}
    if not scoring:
        return [
            RedFlag(
                severity="high",
                title="No score",
                detail="Scoring failed; the verdict has nothing to stand on",
                rule="confidence",
            )
        ]
    flags = []
    if scoring.get("confidence") == "Low":
        flags.append(
            RedFlag(
                severity="medium",
                title="Low score confidence",
                detail=f"Confidence {scoring.get('confidence_score', 0):.0%}: too little data to trust the score",
                rule="confidence",
            )
        )
    thin = [
        f"{name} {dim.get('data_coverage', 0):.0%}"
        for name, dim in (scoring.get("dimensions") or {}).items()
        if (dim.get("data_coverage") or 0) < DATA_COVERAGE_MIN
    ]
    missing = [
        name
        for name in ("technical", "fundamental", "risk", "valuation")
        if name not in (scoring.get("dimensions") or {})
    ]
    if thin or missing:
        parts = []
        if thin:
            parts.append("low coverage: " + ", ".join(thin))
        if missing:
            parts.append("missing: " + ", ".join(missing))
        flags.append(
            RedFlag(
                severity="low",
                title="Thin data coverage",
                detail="; ".join(parts),
                rule="coverage",
            )
        )
    return flags


def check_freshness(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    warnings = (report.get("data_freshness") or {}).get("warnings") or []
    return [
        RedFlag(severity="medium", title="Stale data", detail=w, rule="freshness") for w in warnings
    ]


def check_currency_mismatch(report: Dict[str, Any], today: datetime) -> List[RedFlag]:
    """Statements in another currency that the pipeline could not convert."""
    info = report.get("info") or {}
    listing = info.get("currency")
    statements = info.get("financial_currency")
    if not listing or not statements or statements == listing:
        return []
    if ((report.get("currency_conversion") or {}).get("rate")) is not None:
        return []  # converted into the listing currency before analysis
    return [
        RedFlag(
            severity="medium",
            title="Statements in a different currency",
            detail=(
                f"Trades in {listing}, reports in {statements}, and no FX rate was "
                "available: DCF, FCF yield and Monte Carlo values mix currencies"
            ),
            rule="currency_mismatch",
        )
    ]


RULES: List[Callable[[Dict[str, Any], datetime], List[RedFlag]]] = [
    check_beneish,
    check_altman,
    check_negative_fcf,
    check_dilution,
    check_dividend_coverage,
    check_interest_coverage,
    check_statement_age,
    check_confidence,
    check_freshness,
    check_currency_mismatch,
]


# ==================== Helpers ====================


def share_growth_per_year(shares: List[Optional[float]], periods: List[str]) -> Optional[float]:
    """
    Annualized change in share count (percent/yr) over up to the last 3 years.

    Lists are most recent first. Uses the oldest usable value within 3 years
    of the latest so a single missing year doesn't hide the trend.
    """
    points = [(p, s) for p, s in zip(periods, shares, strict=False) if s is not None and s > 0][:4]
    if len(points) < 2:
        return None
    (latest_period, latest), (oldest_period, oldest) = points[0], points[-1]
    try:
        years = (
            datetime.fromisoformat(str(latest_period)[:10])
            - datetime.fromisoformat(str(oldest_period)[:10])
        ).days / 365.25
    except ValueError:
        years = len(points) - 1
    if years < 0.5:
        return None
    return float(((latest / oldest) ** (1 / years) - 1) * 100)


def _report_date(report: Dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(str(report.get("generated_at"))[:19])
    except ValueError:
        return datetime.now()


def _analysis(report: Dict[str, Any]) -> Dict[str, Any]:
    return (report.get("fundamental_analysis") or {}).get("analysis") or {}


def _quality(report: Dict[str, Any]) -> Dict[str, Any]:
    return _analysis(report).get("quality_scores") or {}


def _history(report: Dict[str, Any]) -> Dict[str, Any]:
    return _analysis(report).get("annual_history") or {}


def _is_financial(report: Dict[str, Any]) -> bool:
    sector = str((report.get("info") or {}).get("sector") or "").lower()
    return sector in _FINANCIAL_SECTORS


def _first(values: List[Optional[float]]) -> Optional[float]:
    return _num(values[0]) if values else None


def _num(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return None if math.isnan(result) or math.isinf(result) else result
