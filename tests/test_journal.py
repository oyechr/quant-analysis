"""
Tests for the decision journal, the daily `changes` additions (holdings,
thesis checks, the saved digest, the notification) and the toast helper.
All offline: synthetic rows and prices, or the fake_market fixture.
"""

import json
import subprocess
from datetime import date

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import cli
from src.pipeline import AnalysisOptions
from src.tracking import (
    Decision,
    Outcome,
    add_decision,
    check_journal,
    check_thesis,
    history_row,
    load_history,
    load_journal,
    look_back,
    record_scores,
    render_journal,
    render_look_back,
    render_markdown,
    save_journal,
    snapshot_row,
    summarize_outcomes,
    summary_line,
    track_changes,
)
from src.tracking.journal import period_return
from src.utils import notify
from tests.test_tracking import _flag, _report, _scoring

DAY1 = date(2026, 10, 20)
DAY2 = date(2026, 10, 22)


def _row(day=DAY2, ticker="AAPL", score=60.0, signal="Hold", price=100.0, flags=()):
    return history_row(
        _report(price, "USD"),
        _scoring(ticker=ticker, score=score, signal=signal),
        "test",
        red_flags=list(flags),
        today=day,
    )


def _buy(**kwargs):
    fields = {"ticker": "AAPL", "date": DAY1, "action": "buy", "thesis": "test", **kwargs}
    return Decision(**fields)


# ==================== File ====================


class TestJournalFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "journal.toml"
        decision = _buy(
            thesis='Cheap "vs" peers',
            exit_if="Margins fall",
            price=100.0,
            shares=10,
            stop=90.0,
            target=130.0,
            min_score=50.0,
            review_by=date(2027, 4, 1),
        )
        decision.take_snapshot(
            _row(
                DAY1, flags=[_flag("Altman Z-Score in distress zone", "high"), _flag("Stale data")]
            )
        )
        save_journal([decision], path)

        (loaded,) = load_journal(path)

        assert loaded == decision
        assert loaded.flags == ["Altman Z-Score in distress zone", "Stale data"]
        assert loaded.price == 100.0  # given price kept over the snapshot's

    def test_unusable_number_leaves_the_file_alone(self, tmp_path):
        path = tmp_path / "journal.toml"
        add_decision(path, _buy())
        with pytest.raises(ValueError, match="Not a usable number"):
            add_decision(path, _buy(stop=float("inf")))
        assert len(load_journal(path)) == 1

    def test_first_entries_high_flags_key_and_datetimes(self, tmp_path):
        path = tmp_path / "journal.toml"
        path.write_text(
            '[[decision]]\ndate = 2026-10-20T10:30:00\nticker = "AAPL"\naction = "buy"\n'
            'high_flags = ["Share count dilution"]\nreview_by = 2027-01-01T00:00:00\n',
            encoding="utf-8",
        )
        (d,) = load_journal(path)
        assert (d.date, d.review_by) == (DAY1, date(2027, 1, 1))
        assert d.flags == ["Share count dilution"]
        add_decision(path, Decision("AAPL", DAY2, "sell"))  # compares the dates
        assert load_journal(path)[0].closed == DAY2

    def test_hand_written_entry(self, tmp_path):
        path = tmp_path / "journal.toml"
        path.write_text(
            '[[decision]]\ndate = 2026-10-20\nticker = "eqnr.ol"\naction = "Buy"\n',
            encoding="utf-8",
        )
        (d,) = load_journal(path)
        assert (d.ticker, d.action, d.thesis, d.is_open) == ("EQNR.OL", "buy", None, True)

    def test_bad_entry_raises_value_error(self, tmp_path):
        path = tmp_path / "journal.toml"
        path.write_text('[[decision]]\nticker = "AAPL"\naction = "hold"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="decision 1 needs"):
            load_journal(path)

    def test_missing_file_is_empty(self, tmp_path):
        assert load_journal(tmp_path / "none.toml") == []

    def test_sell_closes_open_buys_and_adds(self, tmp_path):
        path = tmp_path / "journal.toml"
        add_decision(path, _buy())
        add_decision(path, _buy(action="add", date=DAY2))
        add_decision(path, _buy(ticker="MSFT"))

        closed = add_decision(
            path, Decision("AAPL", date(2026, 11, 1), "sell", thesis="Thesis broke")
        )

        assert [d.action for d in closed] == ["buy", "add"]
        decisions = load_journal(path)
        assert [d.is_open for d in decisions] == [False, False, True, False]
        assert decisions[0].closed == date(2026, 11, 1)

    def test_snapshot_row_on_or_before_the_date(self):
        rows = [_row(date(2026, 10, 1)), _row(DAY1, score=55), _row(DAY2, score=70)]
        assert snapshot_row(rows, date(2026, 10, 21))["score"] == 55
        assert snapshot_row(rows, date(2026, 10, 9)) is None  # more than a week old


# ==================== Thesis check ====================


class TestCheckThesis:
    def test_intact(self):
        assert check_thesis(_buy(stop=90, min_score=50), _row(), DAY2) == ([], [])

    def test_broken(self):
        decision = _buy(stop=95, min_score=55)
        decision.take_snapshot(_row(DAY1, flags=[_flag("Share count dilution", "high")]))
        current = _row(
            score=40,
            signal="Sell",
            price=90,
            flags=[
                _flag("Share count dilution", "high"),
                _flag("Altman Z-Score in distress zone", "high"),
                _flag("Stale data"),
            ],
        )

        broken, _ = check_thesis(decision, current, DAY2)

        assert broken == [
            "below stop 95 (price 90.00)",
            "score 40 under the minimum 55",
            "signal Hold -> Sell",
            "new high red flag: Altman Z-Score in distress zone",
        ]

    def test_sell_signal_at_the_decision_is_known(self):
        decision = _buy()
        decision.take_snapshot(_row(DAY1, score=45, signal="Sell"))
        assert check_thesis(decision, _row(score=44, signal="Strong Sell"), DAY2) == ([], [])

    def test_warnings(self):
        decision = _buy(target=110, review_by=DAY2)
        decision.take_snapshot(_row(DAY1, score=72))

        broken, warnings = check_thesis(decision, _row(date(2026, 10, 1), price=112), DAY2)

        assert broken == []
        assert warnings == [
            "reached target 110 (price 112.00)",
            "review date 2026-10-22 reached",
            "score 72 -> 60 since 2026-10-20",
            "last scored 2026-10-01",
        ]

    def test_no_score_yet(self):
        assert check_thesis(_buy(), None, DAY2) == ([], ["no score yet: run quant changes"])

    def test_check_journal_uses_latest_row_and_skips_closed(self):
        decisions = [
            _buy(min_score=50),
            _buy(ticker="MSFT"),
            Decision("NVDA", DAY1, "buy", closed=DAY2),
            Decision("AAPL", DAY2, "trim"),
        ]
        history = [_row(DAY1, score=45), _row(DAY2, score=58), _row(DAY2, ticker="MSFT")]

        checks = check_journal(decisions, history, DAY2)

        assert [(c.decision.ticker, c.status) for c in checks] == [("AAPL", "OK"), ("MSFT", "OK")]
        assert checks[0].current["score"] == 58

        broken = check_journal(decisions, history, DAY1)  # only day 1 known then
        assert broken[0].status == "Broken"
        assert broken[0].broken == ["score 45 under the minimum 50"]

    def test_new_only_when_worse_than_the_previous_run(self):
        decisions = [_buy(min_score=50), _buy(ticker="MSFT", min_score=50)]
        history = [
            _row(DAY1, score=45),  # AAPL broken yesterday already
            _row(DAY2, score=44),
            _row(DAY1, ticker="MSFT", score=60),
            _row(DAY2, ticker="MSFT", score=40),
        ]

        checks = {c.decision.ticker: c for c in check_journal(decisions, history, DAY2)}

        assert (checks["AAPL"].previous_status, checks["AAPL"].is_new) == ("Broken", False)
        assert (checks["MSFT"].previous_status, checks["MSFT"].is_new) == ("OK", True)
        # No earlier row since the decision: a broken thesis counts as new
        (first,) = check_journal([_buy(min_score=50, date=DAY2)], history, DAY2)
        assert first.previous_status is None and first.is_new

    def test_previous_status_as_of_that_rows_date(self):
        # The review date falls due today: yesterday's row was still OK then
        decisions = [_buy(review_by=DAY2)]
        history = [_row(DAY1), _row(DAY2)]
        (check,) = check_journal(decisions, history, DAY2)
        assert (check.status, check.previous_status, check.is_new) == ("Check", "OK", True)

    def test_second_run_today_compares_with_the_first(self):
        decisions = [_buy(min_score=50)]
        first_run = [_row(DAY1, score=60), _row(DAY2, score=45)]
        second_run = [_row(DAY1, score=60), _row(DAY2, score=44)]
        (check,) = check_journal(decisions, second_run, DAY2, previous=first_run)
        assert (check.status, check.previous_status, check.is_new) == ("Broken", "Broken", False)

    def test_flag_known_at_the_decision_from_an_old_row(self):
        # Rows before 2026-11 have no high_flags, but their flags list the titles
        old = _row(DAY1, flags=[_flag("Share count dilution", "high")])
        old["high_flags"] = None
        decision = _buy()
        decision.take_snapshot(old)
        now = _row(flags=[_flag("Share count dilution", "high")])
        assert check_thesis(decision, now, DAY2) == ([], [])

    def test_return_needs_same_currency(self):
        decision = _buy(price=100.0)
        decision.currency = "NOK"
        (check,) = check_journal([decision], [_row(price=110)], DAY2)
        assert check.return_pct is None
        decision.currency = "USD"
        (check,) = check_journal([decision], [_row(price=110)], DAY2)
        assert check.return_pct == pytest.approx(10.0)

    def test_render(self, tmp_path):
        decision = _buy(stop=95, price=100.0, exit_if="Margins fall")
        checks = check_journal([decision], [_row(price=90)], DAY2)
        text = render_journal(tmp_path / "j.toml", checks, [Decision("MSFT", DAY1, "sell")])
        assert "AAPL  BROKEN (new)  (buy 2026-10-20)" in text
        assert "exit if: Margins fall" in text and "-10.0%" in text
        assert "sell  MSFT" in text


# ==================== Look-back ====================


def _closes(values, start="2026-10-19"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D", tz="UTC"))


class TestLookBack:
    def test_period_return_uses_last_close_on_or_before(self):
        close = _closes([100.0, 110.0, 121.0])  # 19th, 20th, 21st
        assert period_return(close, DAY1, date(2026, 10, 25)) == pytest.approx(10.0)
        assert period_return(close, date(2026, 10, 1), DAY2) is None
        assert period_return(None, DAY1, DAY2) is None

    def test_outcomes_and_summary(self):
        prices = {
            "AAPL": _closes([100.0, 100.0, 120.0, 130.0]),
            "MSFT": _closes([100.0, 100.0, 90.0, 80.0]),
            "^GSPC": _closes([100.0, 100.0, 105.0, 110.0]),
        }
        decisions = [
            _buy(closed=date(2026, 10, 21)),
            _buy(ticker="MSFT"),
            Decision("MSFT", DAY1, "sell", signal="Sell"),
            Decision("AAPL", date(2026, 9, 1), "buy"),
        ]
        for d in decisions[:2]:
            d.signal = "Buy"

        outcomes = look_back(
            decisions, prices.get, lambda t: "^GSPC", today=DAY2, since=date(2026, 10, 1)
        )

        aapl, msft_buy, msft_sell = outcomes
        assert (aapl.ticker_return, aapl.benchmark_return) == (pytest.approx(20), pytest.approx(5))
        assert aapl.good_call is True
        assert msft_buy.excess == pytest.approx(-30) and msft_buy.good_call is False
        assert msft_sell.good_call is True  # it fell after the sale
        summary = {g["group"]: g for g in summarize_outcomes(outcomes)}
        assert summary["buy/add, Buy"]["count"] == 2
        assert summary["buy/add, Buy"]["good_calls"] == 0.5
        assert summary["trim/sell, Sell"]["mean_excess"] == pytest.approx(-30)

        text = render_look_back(outcomes)
        assert "BY SIGNAL AT THE TIME" in text and "+15.0%" in text

    def test_missing_prices(self):
        outcome = Outcome(_buy(), DAY2, "^GSPC", None, 5.0)
        assert outcome.excess is None and outcome.good_call is None
        assert summarize_outcomes([outcome]) == []


# ==================== Daily changes ====================


class TestDailyChanges:
    def test_holdings_marked_and_theses_checked(self, fake_market, tmp_path):
        data_dir = str(tmp_path)
        journal = [_buy(min_score=99, thesis="Needs a high score"), _buy(ticker="MSFT")]

        result = track_changes(
            ["AAPL", "MSFT"],
            options=AnalysisOptions(include_context=False),
            data_dir=data_dir,
            today=DAY2,
            held={"AAPL"},
            journal=journal,
        )

        held = {c.ticker: c.held for c in result.changes}
        assert held == {"AAPL": True, "MSFT": False}
        statuses = {t.decision.ticker: t.status for t in result.theses}
        assert statuses["AAPL"] == "Broken"  # checked against today's new row
        data = result.to_dict()
        assert data["theses"][0]["broken"][0].endswith("under the minimum 99")
        markdown = render_markdown(data)
        assert "## Theses To Recheck" in markdown and "Needs a high score" in markdown
        assert data["theses"][1]["status"] == "OK"  # MSFT: no criteria to break
        assert summary_line(data) == "1 thesis broken"

    def test_summary_line(self):
        quiet = {"changes": [{"ticker": "A", "notes": []}], "theses": []}
        assert summary_line(quiet) is None
        moved = {
            "changes": [{"ticker": t, "notes": ["x"]} for t in "ABCDE"],
            "theses": [
                {"status": "Check", "new": True},
                {"status": "Broken", "new": False},  # already broken last run
                {"status": "OK", "new": False},
            ],
        }
        assert summary_line(moved) == "1 to recheck; 5 worth a look: A, B, C, D, ..."
        failed = {"changes": [{"ticker": "A", "error": "down"}]}
        assert summary_line(failed) == "Nothing scored (1 failed): check the log"

    def test_cli_covers_watchlist_holdings_and_journal(self, fake_market, tmp_path, monkeypatch):
        portfolio = tmp_path / "portfolio.csv"
        portfolio.write_text("ticker,name,account,shares\nMSFT,Microsoft,1,10\n", encoding="utf-8")
        journal = tmp_path / "journal.toml"
        save_journal([_buy(ticker="NVDA", min_score=99)], journal)
        watchlist = tmp_path / "w.toml"
        watchlist.write_text('["AAPL"]\nadded = 2026-10-20\n', encoding="utf-8")
        sent = []
        monkeypatch.setattr(notify, "toast", lambda *args: sent.append(args) or True)

        out = CliRunner().invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "changes",
                "--file",
                str(watchlist),
                "--portfolio",
                str(portfolio),
                "--journal",
                str(journal),
                "--save",
                "--notify",
            ],
        )

        assert out.exit_code == 0, out.output
        assert {r["ticker"] for r in load_history(str(tmp_path))} == {"AAPL", "MSFT", "NVDA"}
        digests = list((tmp_path / "_changes").glob("changes_*"))
        assert sorted(p.suffix for p in digests) == [".json", ".md"]
        data = json.loads(next(p for p in digests if p.suffix == ".json").read_text("utf-8"))
        assert [c["held"] for c in data["changes"] if c["ticker"] == "MSFT"] == [True]
        # NVDA's minimum score is out of reach, so its thesis is broken
        assert [line for _, line, _ in sent] == ["1 thesis broken"]

        # Without the journal, a first run has nothing to report
        quiet = CliRunner().invoke(
            cli,
            [
                *["--output-dir", str(tmp_path / "fresh"), "changes", "--file", str(watchlist)],
                *["--portfolio", str(portfolio), "--journal", str(tmp_path / "none.toml")],
                "--notify",
            ],
        )
        assert quiet.exit_code == 0, quiet.output
        assert len(sent) == 1 and "Nothing worth a notification" in quiet.output

    def test_cli_notifies_with_the_digest(self, fake_market, tmp_path, monkeypatch):
        journal = tmp_path / "journal.toml"
        save_journal([_buy(min_score=99)], journal)
        sent = []
        monkeypatch.setattr(notify, "toast", lambda *args: sent.append(args) or True)

        out = CliRunner().invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "changes",
                "AAPL",
                "--journal",
                str(journal),
                "--save",
                "--notify",
            ],
        )

        assert out.exit_code == 0, out.output
        ((title, line, digest),) = sent
        assert title.startswith("quant changes ") and line == "1 thesis broken"
        assert digest.suffix == ".md" and digest.exists()

        # A second run the same day: still broken, but not news
        again = CliRunner().invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "changes",
                "AAPL",
                "--journal",
                str(journal),
                "--notify",
            ],
        )
        assert again.exit_code == 0, again.output
        assert len(sent) == 1 and "Nothing worth a notification" in again.output

    def test_tickers_given_survive_a_broken_portfolio(self, fake_market, tmp_path, monkeypatch):
        portfolio = tmp_path / "portfolio.csv"
        portfolio.write_text("name\nhalf-written\n", encoding="utf-8")
        base = ["--output-dir", str(tmp_path), "changes", "--portfolio", str(portfolio)]

        out = CliRunner().invoke(cli, [*base, "AAPL"])
        assert out.exit_code == 0, out.output
        assert "Holdings not read" in out.output

        out = CliRunner().invoke(cli, base)  # the holdings are the point: stop
        assert out.exit_code == 1 and "missing column" in out.output


# ==================== Journal CLI ====================


class TestJournalCli:
    def _invoke(self, tmp_path, *args):
        return CliRunner().invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "journal",
                "--journal",
                str(tmp_path / "j.toml"),
                *args,
            ],
        )

    def test_add_scores_now_and_ls(self, fake_market, tmp_path, monkeypatch):

        out = self._invoke(tmp_path, "add", "aapl", "--thesis", "Moat", "--min-score", "10")
        assert out.exit_code == 0, out.output
        assert "Recorded buy AAPL" in out.output and "score " in out.output

        (d,) = load_journal(tmp_path / "j.toml")
        assert d.score is not None and d.price is not None and d.preset == "default"
        assert load_history(str(tmp_path), "AAPL")[0]["source"] == "journal"

        out = self._invoke(tmp_path, "ls")
        assert out.exit_code == 0, out.output
        assert "JOURNAL" in out.output and "OK" in out.output

    def test_add_warns_when_broken_from_the_start(self, fake_market, tmp_path, monkeypatch):
        out = self._invoke(tmp_path, "add", "AAPL", "--thesis", "x", "--min-score", "99")
        assert out.exit_code == 0, out.output
        assert "Broken from the start: score" in out.output and "under the minimum 99" in out.output

    def test_buy_needs_a_thesis_unless_watched(self, tmp_path, monkeypatch):
        out = self._invoke(tmp_path, "add", "AAPL", "--date", "2026-10-20")
        assert out.exit_code != 0 and "needs a thesis" in out.output

        (tmp_path / "watchlist.toml").write_text(
            '["AAPL"]\nthesis = "From the watchlist"\nadded = 2026-10-01\nstop = 90.0\n',
            encoding="utf-8",
        )
        record_scores([_row(DAY1)], str(tmp_path))
        out = self._invoke(tmp_path, "add", "AAPL", "--date", "2026-10-20")
        assert out.exit_code == 0, out.output
        (d,) = load_journal(tmp_path / "j.toml")
        assert (d.thesis, d.stop, d.score) == ("From the watchlist", 90.0, 60.0)

    def test_sell_closes_and_lookback(self, fake_market, tmp_path, monkeypatch):
        save_journal([_buy(date=date(2026, 6, 1))], tmp_path / "j.toml")

        out = self._invoke(tmp_path, "add", "AAPL", "--action", "sell", "--date", "2026-09-01")
        assert out.exit_code == 0, out.output
        assert "Closed the buy of 2026-06-01" in out.output

        out = self._invoke(tmp_path, "lookback", "--json")
        assert out.exit_code == 0, out.output
        outcomes = json.loads(out.output)
        assert [o["decision"]["action"] for o in outcomes] == ["buy", "sell"]
        assert outcomes[0]["end"] == "2026-09-01"

    def test_empty_journal(self, tmp_path):
        assert "is empty" in self._invoke(tmp_path, "ls").output
        assert "No decisions" in self._invoke(tmp_path, "lookback").output

    def test_broken_watchlist_is_a_clean_error(self, tmp_path, monkeypatch):
        (tmp_path / "watchlist.toml").write_text("not [valid", encoding="utf-8")
        out = self._invoke(tmp_path, "add", "AAPL", "--thesis", "x")
        assert out.exit_code == 1 and "Can't read watchlist.toml" in out.output

    def test_bad_number_is_a_clean_error(self, tmp_path, monkeypatch):
        out = self._invoke(tmp_path, "add", "AAPL", "--thesis", "x", "--stop", "inf")
        assert out.exit_code == 2 and "'inf' is not a usable number" in out.output
        assert not (tmp_path / "j.toml").exists()


# ==================== Toast ====================


class TestToast:
    def test_runs_powershell_with_the_text_in_the_environment(self, monkeypatch, tmp_path):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(notify.sys, "platform", "win32")
        monkeypatch.setattr(notify.subprocess, "run", fake_run)

        assert notify.toast("Title <&>", "2 worth a look", tmp_path / "d.md") is True

        ((args, kwargs),) = calls
        assert args[0] == "powershell.exe" and "-EncodedCommand" in args
        assert kwargs["env"]["QUANT_TOAST_TITLE"] == "Title <&>"
        assert kwargs["env"]["QUANT_TOAST_LAUNCH"].startswith("file:")

    def test_failure_never_raises(self, monkeypatch):
        def broken(*args, **kwargs):
            raise OSError("no powershell")

        monkeypatch.setattr(notify.sys, "platform", "win32")
        monkeypatch.setattr(notify.subprocess, "run", broken)
        assert notify.toast("t", "m") is False

    def test_other_platforms_skip(self, monkeypatch):
        monkeypatch.setattr(notify.sys, "platform", "linux")
        assert notify.toast("t", "m") is False
