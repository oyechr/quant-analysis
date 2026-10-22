"""
Tests for Phase 4 tracking: the watchlist file, the score history, and
`quant changes`. All offline: synthetic reports, or the fake_market fixture.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.cli import cli
from src.pipeline import AnalysisOptions
from src.scoring.dimensions import DimensionResult
from src.scoring.scorer import ScoringResult
from src.screening import resolve_universe
from src.tracking import (
    TickerChange,
    WatchItem,
    add_to_watchlist,
    flag_titles,
    history_path,
    history_row,
    load_history,
    load_watchlist,
    record_scores,
    remove_from_watchlist,
    render_text,
    track_changes,
)
from src.vetting.red_flags import RedFlag

DAY1 = date(2026, 10, 20)
DAY2 = date(2026, 10, 22)


def _scoring(ticker="AAPL", score=60.0, signal="Hold", valuation=50.0, preset="default"):
    return ScoringResult(
        ticker=ticker,
        composite_score=score,
        signal=signal,
        confidence="Medium",
        confidence_score=0.7,
        technical=DimensionResult("technical", 55.0),
        valuation=DimensionResult("valuation", valuation),
        config_name=preset,
    )


def _report(price=100.0, currency="USD"):
    return {"info": {"current_price": price, "currency": currency}}


def _flag(title, severity="medium"):
    return RedFlag(severity=severity, title=title, detail="", rule="test")


def _row(day=DAY1, **kwargs):
    scoring_args = {
        k: kwargs.pop(k) for k in ("ticker", "score", "signal", "valuation") if k in kwargs
    }
    return history_row(
        _report(**kwargs),
        _scoring(**scoring_args),
        "test",
        red_flags=[],
        today=day,
    )


# ==================== Watchlist ====================


class TestWatchlist:
    def test_add_writes_entries_that_read_back(self, tmp_path):
        path = tmp_path / "watchlist.toml"
        added, updated = add_to_watchlist(
            path,
            ["eqnr.ol", "AAPL"],
            thesis='Cheap "vs" peers \\ ø',
            target=450,
            stop=380.5,
            today=DAY1,
        )

        assert added == ["EQNR.OL", "AAPL"] and updated == []
        items = load_watchlist(path)
        assert list(items) == ["EQNR.OL", "AAPL"]
        assert items["EQNR.OL"] == WatchItem("EQNR.OL", DAY1, 'Cheap "vs" peers \\ ø', 450.0, 380.5)

    def test_readding_updates_given_fields_and_keeps_added_date(self, tmp_path):
        path = tmp_path / "watchlist.toml"
        add_to_watchlist(path, ["AAPL"], thesis="Services growth", target=300, today=DAY1)

        added, updated = add_to_watchlist(path, ["AAPL"], stop=200, today=DAY2)

        assert added == [] and updated == ["AAPL"]
        item = load_watchlist(path)["AAPL"]
        assert (item.added, item.thesis, item.target, item.stop) == (
            DAY1,
            "Services growth",
            300.0,
            200.0,
        )

    def test_remove(self, tmp_path):
        path = tmp_path / "watchlist.toml"
        add_to_watchlist(path, ["AAPL", "MSFT"], today=DAY1)

        removed, missing = remove_from_watchlist(path, ["msft", "NVDA"])

        assert removed == ["MSFT"] and missing == ["NVDA"]
        assert list(load_watchlist(path)) == ["AAPL"]

    def test_missing_file_is_empty(self, tmp_path):
        assert load_watchlist(tmp_path / "nope.toml") == {}

    def test_hand_edited_file(self, tmp_path):
        path = tmp_path / "watchlist.toml"
        path.write_text(
            '[AAPL]\nthesis = "typed by hand"\nadded = 2026-10-01\ntarget = 300\n\n["EQNR.OL"]\n',
            encoding="utf-8",
        )

        items = load_watchlist(path)

        assert items["AAPL"].target == 300.0 and items["AAPL"].added == date(2026, 10, 1)
        assert items["EQNR.OL"].thesis is None

    def test_broken_file_raises_value_error(self, tmp_path):
        path = tmp_path / "watchlist.toml"
        path.write_text("[AAPL\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Can't read"):
            load_watchlist(path)

    def test_watchlist_universe(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No tickers"):
            resolve_universe(["watchlist"])

        add_to_watchlist(Path("watchlist.toml"), ["AAPL", "EQNR.OL"])
        universe = resolve_universe(["watchlist", "MSFT"])

        assert universe.tickers == ["AAPL", "EQNR.OL", "MSFT"]
        assert universe.label == "watchlist+tickers"


# ==================== History ====================


class TestHistory:
    def test_row_from_report_and_score(self):
        flags = [
            _flag("Altman Z-Score in distress zone", "high"),
            _flag("Stale data"),
            _flag("Stale data"),
        ]

        row = history_row(_report(123.456), _scoring(), "vet", red_flags=flags, today=DAY1)

        assert row is not None
        assert row["date"] == "2026-10-20" and row["source"] == "vet"
        assert row["score"] == 60.0 and row["technical"] == 55.0 and row["risk"] is None
        assert row["price"] == 123.456 and row["currency"] == "USD"
        assert row["red_flags"] == 3
        assert flag_titles(row) == ["Altman Z-Score in distress zone", "Stale data"]

    def test_no_score_no_row(self):
        assert history_row(_report(), None, "score") is None
        assert history_row({"info": {}}, _scoring(), "score") is None  # unknown symbol

    def test_one_row_per_ticker_preset_and_day(self, tmp_path):
        record_scores([_row(DAY1, score=50), _row(DAY1, ticker="MSFT")], str(tmp_path))
        record_scores([_row(DAY1, score=55), _row(DAY2, score=60)], str(tmp_path))
        record_scores(
            [history_row(_report(), _scoring(preset="value"), "test", [], DAY2)], str(tmp_path)
        )

        aapl = load_history(str(tmp_path), "aapl")
        assert [(r["date"], r["preset"], r["score"]) for r in aapl] == [
            ("2026-10-20", "default", 55.0),
            ("2026-10-22", "default", 60.0),
            ("2026-10-22", "value", 60.0),
        ]
        assert len(load_history(str(tmp_path), preset="default")) == 3

    def test_values_survive_the_csv(self, tmp_path):
        row = history_row(
            _report(99.5, "NOK"), _scoring(), "x", [_flag("Weak interest coverage")], DAY1
        )
        record_scores([row], str(tmp_path))

        (loaded,) = load_history(str(tmp_path))
        assert loaded == row
        assert history_path(str(tmp_path)).read_text(encoding="utf-8").startswith("date,ticker")

    def test_nothing_to_record(self, tmp_path):
        assert record_scores([None], str(tmp_path)) is None
        assert not history_path(str(tmp_path)).exists()


# ==================== Changes ====================


class TestTickerChange:
    def _change(self, previous, current, watch=None, next_earnings=None):
        return TickerChange(
            ticker="AAPL",
            today=DAY2,
            previous=previous,
            current=current,
            watch=watch,
            next_earnings=next_earnings,
        )

    def test_deltas_signal_and_flags(self):
        previous = _row(DAY1, score=58, signal="Hold", valuation=45, price=100)
        previous["flags"] = "Low score confidence | Stale data"
        current = _row(DAY2, score=66, signal="Buy", valuation=60, price=110)
        current["flags"] = "Stale data | Share count dilution"

        change = self._change(previous, current)

        assert change.score_delta == 8
        assert change.price_change_pct == pytest.approx(10.0)
        assert change.signal_change == ("Hold", "Buy")
        assert change.new_flags == ["Share count dilution"]
        assert change.resolved_flags == ["Low score confidence"]
        assert change.notes() == [
            "signal Hold -> Buy",
            "score 58 -> 66 (+8)",
            "dimensions: valuation +15",
            "new red flag: Share count dilution",
            "red flag cleared: Low score confidence",
        ]

    def test_small_moves_are_quiet(self):
        change = self._change(_row(DAY1, score=60), _row(DAY2, score=62))
        assert change.notes() == []

    def test_first_run_has_no_deltas(self):
        change = self._change(None, _row(DAY2))
        assert change.score_delta is None and change.new_flags == [] and change.notes() == []

    def test_price_change_needs_same_currency(self):
        change = self._change(_row(DAY1, currency="USD"), _row(DAY2, price=900, currency="NOK"))
        assert change.price_change_pct is None

    def test_target_and_stop(self):
        watch = WatchItem("AAPL", DAY1, target=104, stop=97)
        change = self._change(_row(DAY1), _row(DAY2, price=100), watch=watch)
        assert change.notes() == ["4.0% below target 104", "3.0% above stop 97"]

        hit = self._change(_row(DAY1), _row(DAY2, price=105), watch=watch)
        assert hit.notes()[0] == "reached target 104 (price 105.00)"
        stopped = self._change(_row(DAY1), _row(DAY2, price=96), watch=watch)
        assert stopped.notes() == ["below stop 97 (price 96.00)"]

    def test_earnings_soon(self):
        soon = self._change(_row(DAY1), _row(DAY2), next_earnings=str(DAY2 + timedelta(days=6)))
        later = self._change(_row(DAY1), _row(DAY2), next_earnings=str(DAY2 + timedelta(days=30)))
        assert soon.notes() == ["earnings 2026-10-28 (6d)"]
        assert later.notes() == []


class TestTrackChanges:
    def test_second_day_reports_what_moved(self, fake_market, tmp_path):
        data_dir = str(tmp_path)
        options = AnalysisOptions(include_context=False)

        first = track_changes(["AAPL", "MSFT"], options=options, data_dir=data_dir, today=DAY1)
        assert [c.previous for c in first.changes] == [None, None]
        assert all(c.current for c in first.changes)

        # Pretend day 1 scored AAPL lower, on another signal, with a red flag since cleared
        rows = load_history(data_dir)
        for row in rows:
            if row["ticker"] == "AAPL":
                row.update(score=row["score"] - 10, signal="Strong Sell", flags="Stale data")
        history_path(data_dir).unlink()
        record_scores(rows, data_dir)

        fake_market.failing.add("BAD")
        watch = {"AAPL": WatchItem("AAPL", DAY1, thesis="test")}
        second = track_changes(
            ["MSFT", "AAPL", "BAD"],
            options=options,
            watchlist=watch,
            data_dir=data_dir,
            today=DAY2,
        )

        aapl, msft, bad = second.changes  # moved first, quiet next, failures last
        assert aapl.ticker == "AAPL" and msft.ticker == "MSFT" and bad.ticker == "BAD"
        assert aapl.score_delta == pytest.approx(10)
        assert aapl.signal_change[0] == "Strong Sell"
        assert "red flag cleared: Stale data" in aapl.notes()
        assert msft.score_delta == 0 and msft.notes() == []
        assert bad.error

        days = [(r["date"], r["ticker"]) for r in load_history(data_dir)]
        assert days.count(("2026-10-22", "AAPL")) == 1 and len(days) == 4

        text = render_text(second.to_dict())
        assert "WORTH A LOOK" in text and "AAPL" in text
        assert "No notable change: MSFT" in text
        assert "Not scored: BAD" in text


# ==================== CLI ====================


class TestCli:
    def test_watchlist_add_ls_rm(self, tmp_path):
        path = str(tmp_path / "w.toml")
        runner = CliRunner()

        out = runner.invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "watchlist",
                "--file",
                path,
                "add",
                "aapl",
                "--target",
                "300",
            ],
        )
        assert out.exit_code == 0, out.output
        assert "Added AAPL" in out.output

        record_scores([_row(DAY1, score=61, signal="Hold")], str(tmp_path))
        out = runner.invoke(cli, ["--output-dir", str(tmp_path), "watchlist", "--file", path, "ls"])
        assert out.exit_code == 0, out.output
        assert "61 Hold" in out.output and "300" in out.output

        out = runner.invoke(cli, ["watchlist", "--file", path, "rm", "AAPL", "MSFT"])
        assert "Removed AAPL" in out.output and "Not on the watchlist: MSFT" in out.output

    def test_changes_needs_tickers(self, tmp_path):
        out = CliRunner().invoke(cli, ["changes", "--file", str(tmp_path / "w.toml")])
        assert out.exit_code != 0
        assert "quant watchlist add" in out.output

    def test_changes_on_watchlist_json(self, fake_market, tmp_path):
        path = tmp_path / "w.toml"
        add_to_watchlist(path, ["AAPL"], target=1000)

        out = CliRunner().invoke(
            cli,
            ["--output-dir", str(tmp_path), "changes", "--file", str(path), "--json"],
        )

        assert out.exit_code == 0, out.output
        data = json.loads(out.output)
        assert data["changes"][0]["ticker"] == "AAPL"
        assert data["changes"][0]["target"] == 1000
        assert load_history(str(tmp_path), "AAPL")[0]["source"] == "changes"

    def test_screen_records_history_and_adds_to_watchlist(self, fake_market, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        add_to_watchlist(Path("watchlist.toml"), ["MSFT"], thesis="mine")

        out = CliRunner().invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "screen",
                "AAPL",
                "MSFT",
                "NVDA",
                "--top",
                "3",
                "--no-save",
                "--add-to-watchlist",
                "3",
            ],
        )

        assert out.exit_code == 0, out.output
        assert "(1 already listed)" in out.output
        items = load_watchlist(Path("watchlist.toml"))
        assert set(items) == {"AAPL", "MSFT", "NVDA"}
        assert items["MSFT"].thesis == "mine"
        assert items["AAPL"].thesis.startswith("screen tickers (default): ")
        assert {r["source"] for r in load_history(str(tmp_path))} == {"screen"}


def test_chat_context_includes_score_history():
    from src.llm import build_brief_context

    row = _row(DAY1, score=58, signal="Hold")
    row["flags"] = "Share count dilution"

    context = build_brief_context({"ticker": "AAPL", "info": {}}, red_flags=[], score_history=[row])

    assert "SCORE HISTORY" in context
    assert "2026-10-20 [default]: 58.0 Hold" in context and "Share count dilution" in context
