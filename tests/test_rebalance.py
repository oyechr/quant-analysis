"""
Tests for rebalance proposals (src/portfolio/rebalance.py). Tickers, amounts
and accounts are made up; real holdings never go in tests.
"""

import json

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import cli
from src.data_fetcher import DataFetcher
from src.pipeline import AnalysisOptions
from src.portfolio import (
    Holding,
    HoldingReview,
    Limits,
    TargetSettings,
    load_portfolio,
    propose_trades,
    rebalance_portfolio,
    render_proposal_text,
    review_portfolio,
)
from src.portfolio.rebalance import AF_TAX_RATE, BUY, SELL, buy_account
from src.portfolio.review import ADD, CHECK, EXIT, HOLD, REVIEW, TRIM, AccountPosition
from src.portfolio.targets import TickerTarget

LOOSE = dict(max_position=1.0, max_sector=1.0, min_trade=0.0, max_new=3)


def _r(
    ticker,
    action=HOLD,
    value=10_000.0,
    price=100.0,
    target=None,
    sector=None,
    score=55.0,
    call="Watch",
    positions=None,
    **kwargs,
):
    """A reviewed holding worth `value` at `price` a share (base currency)."""
    shares = value / price
    holding = Holding(
        ticker,
        ticker,
        shares,
        kwargs.pop("cost", None),
        "NOK",
        accounts=[p.account for p in positions or []],
        positions=positions or [],
    )
    flags = kwargs.pop("flags", [])
    return HoldingReview(
        holding=holding,
        action=action,
        reasons=[f"{action} reason"],
        vet={
            "header": {"score": score, "signal": "Hold"},
            "verdict": {"call": call},
            "red_flags": [{"severity": "high", "title": f} for f in flags],
        },
        sector=sector or f"Sector {ticker}",
        price=price,
        price_base=price,
        cost_price=price,
        value=value,
        target_weight=target,
        **kwargs,
    )


def _candidate(ticker, score, call="Look deeper", price=50.0, **kwargs):
    c = _r(ticker, value=0.0, price=price, score=score, call=call, **kwargs)
    c.holding.shares = 0.0
    c.value = None
    return c


def _propose(holdings, candidates=(), cash=0.0, **limits):
    settings = TargetSettings(limits=Limits(**{**LOOSE, **limits}))
    return propose_trades(list(holdings), list(candidates), settings, cash)


def _trades(proposal, side=None):
    return {t.ticker: t for t in proposal.trades if side is None or t.side == side}


class TestSteps:
    def test_exit_sells_everything_even_under_the_minimum(self):
        p = _propose(
            [_r("OUT", EXIT, value=500.0, target=0.0), _r("A", value=9500.0)], min_trade=2000
        )
        trade = _trades(p)["OUT"]
        assert (trade.side, trade.shares, trade.amount) == (SELL, 5, 500.0)
        assert p.shares_after.get("OUT") is None
        assert p.proceeds == 500.0 and p.cash_left == 500.0

    def test_review_and_check_never_trade(self):
        p = _propose(
            [
                _r("FLAG", REVIEW, value=8000.0, target=0.1, flags=["Altman"]),
                _r("NODATA", CHECK, value=2000.0, target=0.1),
            ],
            max_position=0.2,
        )
        assert p.trades == []

    def test_trim_sells_down_to_target_in_whole_shares(self):
        p = _propose([_r("BIG", TRIM, value=6000.0, target=0.25), _r("A", value=4000.0)])
        trade = _trades(p)["BIG"]
        assert trade.shares == 35  # 6000 - 2500 = 3500 at 100 a share
        assert p.shares_after["BIG"] == 25

    def test_trim_at_target_is_noted(self):
        p = _propose([_r("PAIR", TRIM, value=2000.0, target=0.3), _r("A", value=8000.0)])
        assert p.trades == []
        assert "PAIR: Trim, but already at its target" in p.notes[0]

    def test_a_hold_above_the_position_limit_is_cut(self):
        p = _propose([_r("BIG", value=5000.0, target=0.5), _r("A", value=5000.0)], max_position=0.4)
        assert _trades(p)["BIG"].amount == 1000.0
        assert "above the 40% position limit" in _trades(p)["BIG"].reason

    def test_a_tickers_own_cap_wins(self):
        settings = TargetSettings(limits=Limits(**LOOSE))
        settings.tickers["BIG"] = TickerTarget(max=0.3)
        p = propose_trades([_r("BIG", value=5000.0), _r("A", value=5000.0)], [], settings)
        assert _trades(p)["BIG"].amount == 2000.0

    def test_sector_limit_sells_the_lowest_score_first(self):
        holdings = [
            _r("E1", value=3000.0, sector="Energy", score=70.0),
            _r("E2", value=3000.0, sector="Energy", score=50.0),
            _r("T", value=4000.0, sector="Tech"),
        ]
        p = _propose(holdings, max_sector=0.4)
        assert list(_trades(p)) == ["E2"]
        assert _trades(p)["E2"].amount == 2000.0
        assert "Energy above the 40% sector limit" in _trades(p)["E2"].reason

    def test_funds_are_exempt_from_the_sector_limit(self):
        p = _propose([_r("F", value=8000.0, sector="Fund"), _r("A", value=2000.0)], max_sector=0.4)
        assert p.trades == []

    def test_adds_buy_the_largest_shortfall_first_within_the_cash(self):
        holdings = [
            _r("OUT", EXIT, value=1500.0, target=0.0),
            _r("SMALL", ADD, value=1000.0, target=0.2),  # short 1000
            _r("TINY", ADD, value=500.0, target=0.15),  # short 1000 of 10,000
            _r("A", value=7000.0, target=0.65),
        ]
        p = _propose(holdings, cash=0.0)
        buys = _trades(p, BUY)
        # 1500 raised: the first Add takes its 1000, the next what's left
        assert buys["SMALL"].amount == 1000.0 and buys["TINY"].amount == 500.0
        assert p.cash_left == pytest.approx(0.0)

    def test_cash_reserve_is_kept(self):
        p = _propose([_r("A", ADD, value=5000.0, target=0.9)], cash=5000.0, cash_reserve=3000.0)
        assert _trades(p)["A"].amount == 2000.0
        assert p.cash_left == 3000.0

    def test_small_trades_are_dropped(self):
        p = _propose([_r("A", ADD, value=9000.0, target=0.95)], cash=1000.0, min_trade=2000)
        assert p.trades == []
        assert "the gap is under the minimum trade" in p.notes[0]


class TestCandidates:
    def _holdings(self):
        return [_r("A", value=6000.0, target=0.2), _r("B", value=4000.0, target=0.1)]

    def test_best_look_deeper_names_first_up_to_max_new(self):
        candidates = [
            _candidate("LOW", 61.0),
            _candidate("TOP", 75.0),
            _candidate("MID", 68.0),
            _candidate("WATCH", 80.0, call="Watch"),
            _candidate("TWIN", 90.0, moves_with=("A", 0.93)),
            _candidate("ETF", 85.0, is_fund=True),
        ]
        p = _propose(self._holdings(), candidates, cash=10_000.0, max_new=2)
        buys = _trades(p, BUY)
        assert set(buys) == {"TOP", "MID"}
        assert all(t.new for t in buys.values())
        # median target 15% of 20,000 = 3000 each
        assert buys["TOP"].amount == 3000.0 and buys["TOP"].shares == 60
        notes = "\n".join(p.notes)
        assert "WATCH: not bought (verdict Watch)" in notes
        assert "TWIN: not bought (moves with A (0.93))" in notes
        assert "ETF: not bought (a fund" in notes
        assert "LOW: not bought (already 2 new names)" in notes

    def test_candidates_fit_the_cash_and_the_sector_limit(self):
        candidates = [_candidate("NEW", 70.0, sector="Sector A")]
        p = _propose(self._holdings(), candidates, cash=10_000.0, max_sector=0.35)
        # Sector A holds 6000 of 20,000; the limit leaves 1000
        assert _trades(p)["NEW"].amount == 1000.0

    def test_a_candidate_without_cash_is_not_bought(self):
        p = _propose(self._holdings(), [_candidate("NEW", 70.0)], cash=0.0, min_trade=1)
        assert p.trades == []
        assert "too little cash is left" in p.notes[0]


class TestAccounts:
    def test_sales_come_from_ask_first(self):
        positions = [AccountPosition("AF", 30, 50.0), AccountPosition("ASK", 20, 50.0)]
        r = _r("BOTH", TRIM, value=5000.0, target=0.25, positions=positions, cost=50.0)
        p = _propose([r, _r("A", value=5000.0)])
        trades = [t for t in p.trades if t.ticker == "BOTH"]
        # 5000 - 2500 = 2500 to sell = 25 shares: all 20 in ASK, then 5 in AF
        assert [(t.account, t.shares) for t in trades] == [("ASK", 20), ("AF", 5)]
        assert trades[0].tax is None  # ASK
        assert trades[1].tax == pytest.approx(5 * (100 - 50) * AF_TAX_RATE)

    def test_a_loss_in_af_deducts(self):
        r = _r("LOSS", EXIT, value=1000.0, target=0.0, positions=[AccountPosition("AF", 10, 150.0)])
        p = _propose([r, _r("A", value=9000.0)])
        assert p.tax == pytest.approx(10 * (100 - 150) * AF_TAX_RATE)

    def test_cost_in_another_currency_is_converted_at_todays_rate(self):
        # Price 100 NOK = 10 USD; cost 8 USD a share -> 80 NOK, a 20 NOK gain each
        r = _r("USD", EXIT, value=1000.0, target=0.0, positions=[AccountPosition("AF", 10, 8.0)])
        r.cost_price = 10.0
        p = _propose([r, _r("A", value=9000.0)])
        assert p.tax == pytest.approx(10 * 20 * AF_TAX_RATE)

    def test_buy_accounts(self):
        assert buy_account(_r("X", country="Norway")) == "ASK or AF"
        assert buy_account(_r("X", country="United States")) == "AF only (not EEA)"
        assert buy_account(_r("X", country="United Kingdom")) == "AF only (not EEA)"
        assert buy_account(_r("X", is_fund=True)) == "check ASK eligibility"
        assert buy_account(_r("X")) == "AF (country unknown)"


def test_load_portfolio_keeps_each_account(tmp_path):
    path = tmp_path / "portfolio.csv"
    pd.DataFrame(
        [
            ["SMB.OL", "Sample Bank", "ASK", 10, 100.0, "NOK"],
            ["SMB.OL", "Sample Bank", "AF", 30, 200.0, "NOK"],
        ],
        columns=["ticker", "name", "account", "shares", "cost_basis", "currency"],
    ).to_csv(path, index=False)
    (holding,), _ = load_portfolio(path)
    assert [(p.account, p.shares, p.cost_basis) for p in holding.positions] == [
        ("ASK", 10, 100.0),
        ("AF", 30, 200.0),
    ]


# ==================== End to end (fake market) ====================


@pytest.fixture
def rebalance_market(fake_market, price_factory):
    days = 520
    fx = price_factory("USDNOK=X", days=days, seed=1)
    fx["Close"] = 10.0
    fake_market.price_overrides.update(
        {
            "USDNOK=X": fx,
            **{
                t: price_factory(t, days=days, seed=i)
                for i, t in enumerate(("BIG.OL", "TST", "NEW", "ACWI", "OSEBX.OL"))
            },
        }
    )
    fake_market.info_overrides.update(
        {
            "BIG.OL": {"sector": "Energy", "country": "Norway"},
            "TST": {"currentPrice": 50.0},
            "NEW": {"country": "United States"},
        }
    )
    return fake_market


def test_rebalance_portfolio_end_to_end(rebalance_market, tmp_path):
    fetcher = DataFetcher(cache_dir=str(tmp_path))
    options = AnalysisOptions(include_context=False)
    settings = TargetSettings(limits=Limits(max_position=1.0, max_sector=1.0, min_trade=0.0))
    holdings = [
        Holding(
            "BIG.OL", "Big Energy", 100, 80.0, "NOK", ["ASK"], [AccountPosition("ASK", 100, 80.0)]
        ),
        Holding("TST", "Test Corp", 20, 40.0, "USD", ["AF"], [AccountPosition("AF", 20, 40.0)]),
    ]
    review = review_portfolio(
        holdings,
        fetcher=fetcher,
        options=options,
        workers=1,
        data_dir=str(tmp_path),
        targets=settings,
    )
    proposal = rebalance_portfolio(
        review,
        ["NEW", "BIG.OL"],
        settings,
        cash=5000.0,
        fetcher=fetcher,
        options=options,
        workers=1,
        data_dir=str(tmp_path),
    )

    data = proposal.to_dict()
    assert data["cash_left"] == pytest.approx(5000.0 + data["proceeds"] - data["spent"])
    assert data["before"]["volatility"] > 0
    # Every review action has its trade, and the candidate is bought or explained
    exits = {r.holding.ticker for r in review.holdings if r.action == EXIT}
    assert exits <= {t.ticker for t in proposal.trades if t.side == SELL}
    assert "NEW" in {t.ticker for t in proposal.trades} or any(
        n.startswith("NEW:") for n in proposal.notes
    )
    # A held ticker isn't a candidate
    assert not any(n.startswith("BIG.OL: not bought") for n in proposal.notes)
    text = render_proposal_text(data)
    assert "REBALANCE PROPOSAL" in text and "BEFORE / AFTER" in text and "NOTES" in text
    json.dumps(data, default=str)


def test_cli_rebalance(rebalance_market, tmp_path):
    portfolio = tmp_path / "portfolio.csv"
    pd.DataFrame(
        [
            ["BIG.OL", "Big Energy", "ASK", 100, 80.0, "NOK"],
            ["TST", "Test Corp", "AF", 20, 40.0, "USD"],
        ],
        columns=["ticker", "name", "account", "shares", "cost_basis", "currency"],
    ).to_csv(portfolio, index=False)
    result = CliRunner().invoke(
        cli,
        [
            "--output-dir",
            str(tmp_path / "data"),
            "rebalance",
            str(portfolio),
            "--cash",
            "5000",
            "--candidates",
            "NEW",
            "--targets",
            str(tmp_path / "none.toml"),
            "--workers",
            "1",
            "--save",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "REBALANCE PROPOSAL" in result.output
    saved = json.loads((tmp_path / "rebalance.json").read_text(encoding="utf-8"))
    assert saved["cash"] == 5000.0
    assert (tmp_path / "rebalance.md").exists()


def test_mix_lines_skip_moves_that_round_away():
    from src.portfolio.render import _mix_changes

    before = [{"name": "Fund", "weight": 0.112}, {"name": "Energy", "weight": 0.21}]
    after = [{"name": "Fund", "weight": 0.108}, {"name": "Energy", "weight": 0.17}]
    assert _mix_changes(before, after) == [("Energy", 0.21, 0.17)]
