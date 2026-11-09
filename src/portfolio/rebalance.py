"""
Rebalance Proposals

Concrete trades from a portfolio review: sell Exits, trim towards target,
fix positions and sectors over their limits, add to Add holdings, and spend
what's left on the best candidates from the watchlist or `--candidates`.
The steps are explicit and run in order (see `propose_trades`):

1. Exit: sell everything.
2. Review and Check: no trade (look into the flag or the data first).
3. Trim, or above the position limit: sell down to the target or the cap.
4. A sector above its limit: sell its lowest-scoring stocks until it fits.
5. Cash (--cash, plus what the sales raised, minus the reserve) buys Add
   holdings up to their target, largest shortfall first.
6. Then candidates: a Look deeper verdict, not moving with a holding
   (weekly correlation >= 0.80), best score first, at most `max_new`, each
   at the median target weight, cut to fit the limits and the cash.
7. Whole shares only; trades under `min_trade` are dropped (Exits aren't).

Accounts: sales come from ASK (and IPS) first, where gains are tax-free. A
sale in AF shows the estimated tax at `AF_TAX_RATE` (negative for a loss,
which is deductible against gains at the same rate), ignoring the
shielding deduction (skjermingsfradrag) and with the cost converted at
today's FX rate. ASK only takes shares in companies in the EEA, so a buy is
marked "ASK or AF" or "AF only" from the company's country (Yahoo gives the
headquarters, close to but not always the domicile).
"""

import logging
import math
import statistics
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from ..utils.concurrency import DEFAULT_WORKERS, run_concurrently
from ..vetting.vet import LOOK_DEEPER, vet_ticker
from .exposure import MIN_WEEKS, measure_exposure
from .review import (
    ADD,
    CHECK,
    EXIT,
    REDUNDANT_CORRELATION,
    REVIEW,
    TAX_FREE_ACCOUNTS,
    TAXABLE_ACCOUNTS,
    TRIM,
    AccountPosition,
    Holding,
    HoldingReview,
    MarketData,
    PortfolioReview,
    apply_vet,
    has_data,
    is_under_review,
    unlabeled_account_note,
    unlabeled_accounts,
    value_holding,
)
from .targets import EXEMPT_SECTORS, TargetSettings

logger = logging.getLogger(__name__)

AF_TAX_RATE = 0.3784  # 22% on gains, grossed up by 1.72 (2025-2026)
SELL, BUY = "Sell", "Buy"
CASH = "Cash"  # the line for uninvested cash in the after-trade mix

EEA_COUNTRIES = frozenset(
    {
        "Austria",
        "Belgium",
        "Bulgaria",
        "Croatia",
        "Cyprus",
        "Czech Republic",
        "Czechia",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Germany",
        "Greece",
        "Hungary",
        "Iceland",
        "Ireland",
        "Italy",
        "Latvia",
        "Liechtenstein",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Netherlands",
        "Norway",
        "Poland",
        "Portugal",
        "Romania",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Sweden",
    }
)


@dataclass
class Trade:
    ticker: str
    name: str
    side: str  # Sell or Buy
    shares: float
    amount: float  # base currency
    account: str
    reason: str
    tax: Optional[float] = None  # estimated tax on an AF sale (negative: a deductible loss)
    new: bool = False  # a candidate, not a holding

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "side": self.side,
            "shares": self.shares,
            "amount": round(self.amount, 2),
            "account": self.account,
            "reason": self.reason,
            "tax": round(self.tax, 2) if self.tax is not None else None,
            "new": self.new,
        }


@dataclass
class Proposal:
    base_currency: str
    trades: List[Trade] = field(default_factory=list)
    shares_after: Dict[str, float] = field(default_factory=dict)
    cash: float = 0.0  # given
    reserve: float = 0.0
    proceeds: float = 0.0
    spent: float = 0.0
    notes: List[str] = field(default_factory=list)  # trades not made, and why
    warnings: List[str] = field(default_factory=list)  # about the inputs (account types)
    before: Dict[str, Any] = field(default_factory=dict)  # exposure summaries
    after: Dict[str, Any] = field(default_factory=dict)

    @property
    def cash_left(self) -> float:
        return self.cash + self.proceeds - self.spent

    @property
    def tax(self) -> float:
        """Net estimated AF tax: gains less deductible losses."""
        return sum(t.tax or 0.0 for t in self.trades)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_currency": self.base_currency,
            "trades": [t.to_dict() for t in self.trades],
            "shares_after": self.shares_after,
            "cash": self.cash,
            "reserve": self.reserve,
            "proceeds": round(self.proceeds, 2),
            "spent": round(self.spent, 2),
            "cash_left": round(self.cash_left, 2),
            "tax": round(self.tax, 2),
            "notes": self.notes,
            "warnings": self.warnings,
            "before": self.before,
            "after": self.after,
        }


# ==================== Trades ====================


def propose_trades(
    holdings: List[HoldingReview],
    candidates: List[HoldingReview],
    settings: TargetSettings,
    cash: float = 0.0,
    base_currency: str = "NOK",
) -> Proposal:
    """
    The trades for one review, in the order of the module docstring.

    `holdings` come from `review_portfolio` (actions, targets, values and
    prices in the base currency); `candidates` are vetted reviews with no
    shares. Amounts are in the base currency; targets are fractions of the
    holdings plus the cash.
    """
    limits = settings.limits
    proposal = Proposal(base_currency=base_currency, cash=cash, reserve=limits.cash_reserve)
    valued = [r for r in holdings if r.value and r.price_base]
    total = sum(r.value or 0.0 for r in valued) + cash
    amounts: Dict[str, float] = {r.holding.ticker: r.value or 0.0 for r in valued}
    shares: Dict[str, float] = {r.holding.ticker: r.holding.shares for r in holdings}
    # Shares left per account, reduced by every sale (a holding can be trimmed
    # and then sold again for its sector)
    accounts: Dict[str, List[AccountPosition]] = {
        r.holding.ticker: [replace(p) for p in r.holding.positions] for r in holdings
    }
    proposal.warnings = [
        unlabeled_account_note(a) for a in unlabeled_accounts(r.holding for r in valued)
    ]
    sectors: Dict[str, str] = {r.holding.ticker: r.sector or "Unknown" for r in valued}
    if total <= 0:
        proposal.shares_after = shares
        return proposal

    def cap(ticker: str) -> float:
        own = settings.tickers.get(ticker)
        return own.max if own and own.max is not None else limits.max_position

    def sector_total(sector: str) -> float:
        return sum(a for t, a in amounts.items() if sectors.get(t) == sector)

    def sell(r: HoldingReview, amount: float, reason: str, everything: bool = False) -> float:
        ticker, price = r.holding.ticker, r.price_base or 0.0
        n = shares[ticker] if everything else min(shares[ticker], math.floor(amount / price))
        value = n * price
        if n <= 0 or (not everything and value < limits.min_trade):
            if amount > 0:
                proposal.notes.append(f"{ticker}: {reason}, but the sale is under the minimum")
            return 0.0
        shares[ticker] -= n
        amounts[ticker] -= value
        proposal.proceeds += value
        proposal.trades += _sell_by_account(r, n, reason, accounts[ticker])
        return value

    def buy(r: HoldingReview, amount: float, reason: str) -> float:
        ticker, price = r.holding.ticker, r.price_base or 0.0
        sector = r.sector or "Unknown"
        room = [amount, cap(ticker) * total - amounts.get(ticker, 0.0), available()]
        if sector not in EXEMPT_SECTORS:
            room.append(limits.max_sector * total - sector_total(sector))
        n = math.floor(max(0.0, min(room)) / price) if price > 0 else 0
        value = n * price
        if value < limits.min_trade:
            if amount < limits.min_trade:
                why = "the gap is under the minimum trade"
            elif available() < limits.min_trade:
                why = "too little cash is left"
            else:
                why = "the position or sector limit leaves too little room"
            proposal.notes.append(f"{ticker}: {reason}, but {why}")
            return 0.0
        shares[ticker] = shares.get(ticker, 0.0) + n
        amounts[ticker] = amounts.get(ticker, 0.0) + value
        sectors[ticker] = sector
        proposal.spent += value
        proposal.trades.append(
            Trade(
                ticker,
                r.holding.name,
                BUY,
                n,
                value,
                buy_account(r),
                reason,
                new=r.holding.shares == 0,
            )
        )
        return value

    def available() -> float:
        return max(0.0, proposal.cash_left - limits.cash_reserve)

    # 1. Exit
    for r in valued:
        if r.action == EXIT:
            sell(r, amounts[r.holding.ticker], f"Exit: {_first(r.reasons)}", everything=True)

    # 2. Review and Check: no trade. 3. Trim and the position limit
    frozen = {
        r.holding.ticker
        for r in valued
        if r.action in (REVIEW, CHECK) or is_under_review(r) or not has_data(r)
    }
    for r in valued:
        ticker = r.holding.ticker
        if r.action == EXIT or ticker in frozen:
            continue
        target = (r.target_weight or 0.0) * total
        limit = cap(ticker) * total
        if amounts[ticker] > limit:
            sell(r, amounts[ticker] - limit, f"above the {cap(ticker):.0%} position limit")
        elif r.action == TRIM and amounts[ticker] > target:
            sell(r, amounts[ticker] - target, f"Trim to target {r.target_weight or 0:.1%}")
        elif r.action == TRIM:
            proposal.notes.append(f"{ticker}: Trim, but already at its target; {_first(r.reasons)}")

    # 4. Sector limit: the lowest-scoring stocks go first
    for sector in sorted(set(sectors.values()) - set(EXEMPT_SECTORS)):
        over = sector_total(sector) - limits.max_sector * total
        if over <= 0:
            continue
        reason = f"{sector} above the {limits.max_sector:.0%} sector limit"
        sellable = [
            r
            for r in valued
            if sectors[r.holding.ticker] == sector
            and r.holding.ticker not in frozen
            and shares[r.holding.ticker] > 0
        ]
        for r in sorted(sellable, key=lambda r: r.score or 0.0):
            # What whole-share rounding leaves over isn't a sale to note
            if over < max(limits.min_trade, 1e-9):
                break
            if over < (r.price_base or 0.0):
                continue
            over -= sell(r, min(over, amounts[r.holding.ticker]), reason)

    # 5. Add holdings, largest shortfall first
    shortfalls = [
        (r, (r.target_weight or 0.0) * total - amounts[r.holding.ticker])
        for r in valued
        if r.action == ADD
    ]
    for r, shortfall in sorted(shortfalls, key=lambda rs: rs[1], reverse=True):
        if shortfall > 0:
            buy(r, shortfall, f"Add to target {r.target_weight or 0:.1%}")

    # 6. Candidates
    targets = [r.target_weight for r in valued if r.target_weight]
    size = statistics.median(targets) * total if targets else 0.0
    bought = 0
    for c in sorted(candidates, key=lambda c: c.score or 0.0, reverse=True):
        ticker = c.holding.ticker
        why_not = _not_a_buy(c, held=ticker in amounts)
        if why_not:
            proposal.notes.append(f"{ticker}: not bought ({why_not})")
        elif bought >= limits.max_new:
            proposal.notes.append(f"{ticker}: not bought (already {limits.max_new} new names)")
        elif buy(c, size, f"new: {c.call} {c.score or 0:.0f}/100") > 0:
            bought += 1

    proposal.shares_after = {t: n for t, n in shares.items() if n > 0}
    return proposal


def _not_a_buy(c: HoldingReview, held: bool) -> Optional[str]:
    if held:
        return "already held"
    if c.error or not c.vet:
        return f"no data: {c.error or 'not vetted'}"
    if c.is_fund:
        return "a fund; add it to the portfolio file to size it"
    if c.call != LOOK_DEEPER:
        return f"verdict {c.call}"
    if c.moves_with:
        return f"moves with {c.moves_with[0]} ({c.moves_with[1]:.2f})"
    if not c.price_base:
        return "no price"
    return None


def _sell_by_account(
    r: HoldingReview, n: float, reason: str, left: List[AccountPosition]
) -> List[Trade]:
    """
    Split a sale over the accounts, tax-free ones first, with the tax on AF
    sales. `left` is the shares still held per account; it's reduced.
    """
    h = r.holding
    price = r.price_base or 0.0
    positions = sorted(left, key=lambda p: 0 if p.account.upper() in TAX_FREE_ACCOUNTS else 1)
    if not positions:
        return [Trade(h.ticker, h.name, SELL, n, n * price, ", ".join(h.accounts), reason)]
    trades = []
    remaining = n
    for position in positions:
        part = min(remaining, position.shares)
        if part <= 0:
            continue
        remaining -= part
        position.shares -= part
        tax = None
        cost = position.cost_basis or h.cost_basis
        if position.account.upper() in TAXABLE_ACCOUNTS and cost and r.cost_price:
            # Cost in the base currency, converted at today's rate. A loss is
            # deductible at the same rate, so its "tax" is negative.
            gain = part * (price - cost * price / r.cost_price)
            tax = gain * AF_TAX_RATE
        trades.append(
            Trade(h.ticker, h.name, SELL, part, part * price, position.account, reason, tax)
        )
    return trades


def buy_account(r: HoldingReview) -> str:
    """Where a buy can go: ASK only takes shares in EEA companies."""
    if r.is_fund:
        return "check ASK eligibility"
    if not r.country:
        return "AF (country unknown)"
    return "ASK or AF" if r.country in EEA_COUNTRIES else "AF only (not EEA)"


def _first(reasons: List[str]) -> str:
    return reasons[0] if reasons else ""


# ==================== Orchestration ====================


def rebalance_portfolio(
    review: PortfolioReview,
    candidates: List[str],
    settings: TargetSettings,
    cash: float = 0.0,
    fetcher: Optional[DataFetcher] = None,
    options: Optional[AnalysisOptions] = None,
    workers: int = DEFAULT_WORKERS,
    data_dir: str = "data",
    progress: Optional[Callable[[str, Optional[Exception]], None]] = None,
) -> Proposal:
    """Vet the candidates, propose trades, and measure the exposure after them."""
    fetcher = fetcher or DataFetcher(cache_dir=data_dir)
    options = options or AnalysisOptions(include_context=False)
    market = MarketData(fetcher, review.base_currency, options.use_cache)
    held = {r.holding.ticker: r for r in review.holdings}
    wanted = list(dict.fromkeys(c.upper() for c in candidates))
    vetted = _vet_candidates(
        [t for t in wanted if t not in held],
        fetcher,
        options,
        workers,
        data_dir,
        progress,
    )
    exposure = review.exposure
    closes = dict(exposure.closes) if exposure else {}
    local = dict(exposure.local_closes) if exposure else {}
    for c in vetted:
        value_holding(c, review.base_currency, market.rate)
        ticker = c.holding.ticker
        own = market.closes(ticker)
        converted = market.base_closes(ticker, c.listing_currency) if c.listing_currency else None
        if own is None or converted is None:
            continue
        closes[ticker], local[ticker] = converted, own
        if exposure is not None:
            c.moves_with = _moves_with(converted, exposure.returns)

    proposal = propose_trades(review.holdings, vetted, settings, cash, review.base_currency)
    proposal.notes += [
        f"{t}: not bought as a new name (already held; its action is {held[t].action})"
        for t in wanted
        if t in held
    ]
    proposal.before = review.summary.get("exposure") or {}
    after = _after_trades([*review.holdings, *vetted], proposal.shares_after, proposal.cash_left)
    benchmarks = exposure.benchmarks if exposure else market.benchmarks()
    proposal.after = _with_cash(
        measure_exposure(after, closes, benchmarks, local).summary,
        1.0 - sum(r.weight or 0.0 for r in after),
    )
    return proposal


def _vet_candidates(
    tickers: List[str],
    fetcher: DataFetcher,
    options: AnalysisOptions,
    workers: int,
    data_dir: str,
    progress: Optional[Callable[[str, Optional[Exception]], None]],
) -> List[HoldingReview]:
    def vet(ticker: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        result = vet_ticker(ticker, fetcher=fetcher, options=options, data_dir=data_dir)
        return result.to_dict(), result.report.get("info") or {}

    reviews = []
    for ticker, outcome, error in run_concurrently(vet, tickers, workers=workers):
        review = HoldingReview(holding=Holding(ticker, ticker, 0.0, None, ""))
        if error is not None or outcome is None:
            review.error = str(error or "no result")
        else:
            data, info = outcome
            review.holding.name = str(info.get("name") or ticker)
            apply_vet(review, data, info)
        reviews.append(review)
        if progress:
            progress(ticker, error)
    return reviews


def _moves_with(closes: pd.Series, returns: pd.DataFrame) -> Optional[Tuple[str, float]]:
    """The holding a candidate moves with most (weekly correlation >= the threshold)."""
    weekly = closes.resample("W-FRI").last().pct_change(fill_method=None).rename("_candidate")
    joined = pd.concat([weekly, returns], axis=1, join="inner")
    best: Optional[Tuple[str, float]] = None
    for ticker in returns.columns:
        pair = joined[["_candidate", ticker]].dropna()
        if len(pair) < MIN_WEEKS:
            continue
        corr = float(pair["_candidate"].corr(pair[ticker]))
        if (
            math.isfinite(corr)
            and corr >= REDUNDANT_CORRELATION
            and (best is None or corr > best[1])
        ):
            best = (str(ticker), corr)
    return best


def _after_trades(
    reviews: List[HoldingReview], shares: Dict[str, float], cash: float = 0.0
) -> List[HoldingReview]:
    """
    Copies of the reviews valued at the post-trade share counts. Weights are
    of the holdings plus the cash left, the basis the limits are set on.
    """
    after = []
    for r in reviews:
        n = shares.get(r.holding.ticker, 0.0)
        value = n * (r.price_base or 0.0)
        after.append(replace(r, value=value or None, beta=None, risk_share=None))
    total = sum(r.value or 0.0 for r in after) + max(0.0, cash)
    for r in after:
        r.weight = (r.value or 0.0) / total if total and r.value else None
    return after


def _with_cash(summary: Dict[str, Any], cash_share: float) -> Dict[str, Any]:
    """The cash left as its own line in the sector, country and currency mix."""
    if cash_share < 0.0005:  # it would show as 0.0%
        return summary
    for key in ("by_sector", "by_country", "by_currency"):
        if key in summary:
            summary[key] = [*summary[key], {"name": CASH, "weight": cash_share, "risk": 0.0}]
    return summary
