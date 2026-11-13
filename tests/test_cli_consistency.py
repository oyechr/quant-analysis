"""
CLI consistency (review Batch F): stdout is the result, failures exit
non-zero with a message instead of a traceback, bad options are usage
errors, and every command uses the watchlist chosen with `quant --watchlist`.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import cli
from src.tracking import add_to_watchlist, load_history, load_watchlist

REPO = Path(__file__).resolve().parents[1]


def _run(*args: str):
    return CliRunner().invoke(cli, list(args))


def _clean_exit(result, code: int) -> None:
    """Exited with `code` through click (a message, not a traceback)."""
    assert result.exit_code == code, result.output
    assert isinstance(result.exception, SystemExit), result.exception


# ==================== Nothing scored ====================


def test_report_on_unknown_symbol_fails_without_a_score(fake_market, tmp_path):
    fake_market.failing.add("BADSYM")
    result = _run("--output-dir", str(tmp_path), "report", "BADSYM")
    _clean_exit(result, 1)
    assert "No data for BADSYM" in result.stderr
    assert "Composite Score" not in result.stdout  # no meaningless 50/100 Hold
    assert load_history(str(tmp_path)) == []


def test_report_progress_goes_to_stderr(fake_market, tmp_path):
    result = _run("--output-dir", str(tmp_path), "report", "AAPL")
    assert result.exit_code == 0, result.output
    assert "STOCK SCORE: AAPL" in result.stdout
    assert "Generating report" in result.stderr and "Generating report" not in result.stdout
    assert "Files saved in" in result.stderr


def test_score_fails_when_no_ticker_scores(fake_market, tmp_path):
    fake_market.failing.update({"BAD1", "BAD2"})
    result = _run("--output-dir", str(tmp_path), "score", "BAD1", "BAD2")
    _clean_exit(result, 1)
    assert "No ticker could be scored" in result.stderr
    assert "no data (check the symbol)" in result.stderr

    # One good ticker is enough
    result = _run("--output-dir", str(tmp_path), "score", "BAD1", "AAPL")
    assert result.exit_code == 0, result.output


def test_discover_fails_when_nothing_is_fetched(tmp_path):
    with patch("src.discovery.sources.Edgar13FSource.fetch_portfolios", return_value=[]):
        result = _run("--output-dir", str(tmp_path), "discover")
    _clean_exit(result, 1)
    assert "No portfolios fetched" in result.stderr


def test_screen_fails_only_when_no_data_at_all(fake_market, tmp_path):
    fake_market.failing.update({"BAD1", "BAD2"})
    result = _run("--output-dir", str(tmp_path), "screen", "BAD1", "BAD2", "--no-save")
    _clean_exit(result, 1)
    assert "No ticker could be scored" in result.stderr

    # Filters that leave nothing are a result, not a failure
    result = _run(
        "--output-dir", str(tmp_path), "screen", "AAPL", "MSFT", "--sector", "Mining", "--no-save"
    )
    assert result.exit_code == 0, result.output
    assert "Screening 2 tickers" in result.stderr and "Screening" not in result.stdout


# ==================== JSON on stdout ====================


def _fake_comparator():
    frame = pd.DataFrame({"AAPL": [70.0], "MSFT": [60.0]}, index=["Composite"])
    comparator = MagicMock()
    comparator.side_by_side_scores.return_value = frame
    comparator.relative_valuation.return_value = frame
    comparator.key_metrics_table.return_value = frame
    comparator.correlation_matrix.return_value = pd.DataFrame(
        [[1.0, 0.5], [0.5, 1.0]], index=["AAPL", "MSFT"], columns=["AAPL", "MSFT"]
    )
    comparator.price_data.return_value = {}
    return comparator


@pytest.mark.parametrize("flags", [("compare", "--json"), ("--format", "json", "compare")])
def test_compare_json_is_parseable(flags):
    with patch("src.cli.analyze.TickerComparator", return_value=_fake_comparator()):
        result = _run(*flags, "AAPL", "MSFT")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert {"scores", "relative_valuation", "correlation_matrix"} <= set(data)
    assert "Comparing: AAPL, MSFT" in result.stderr


@pytest.mark.parametrize(
    "weights, message",
    [
        ("0.5,abc", "use numbers"),
        ("0.5,inf", "use numbers"),
        ("0.5,0.3,0.2", "must match"),
        ("0.5,0.6", "must sum to 1.0"),
    ],
)
def test_compare_bad_weights_are_usage_errors(weights, message):
    with patch("src.cli.analyze.TickerComparator") as comparator:
        result = _run("compare", "AAPL", "MSFT", "--weights", weights)
    _clean_exit(result, 2)
    assert message in result.stderr
    comparator.assert_not_called()  # checked before anything is fetched


# ==================== Clean errors ====================


def test_import_portfolio_rejects_a_non_nordnet_file(tmp_path):
    export = tmp_path / "other.csv"
    export.write_text("a,b\n1,2\n", encoding="utf-8")
    result = _run("import-portfolio", str(export), "--out", str(tmp_path / "p.csv"))
    _clean_exit(result, 1)
    assert "not a Nordnet holdings export" in result.stderr


@pytest.mark.parametrize("command", ["review", "rebalance"])
def test_portfolio_missing_a_column_is_a_clean_error(tmp_path, command):
    path = tmp_path / "p.csv"
    path.write_text("name,account\nSome Co,ASK\n", encoding="utf-8")
    result = _run(command, str(path))
    _clean_exit(result, 1)
    assert "missing column(s)" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("watch", "AAPL", "--interval", "0"),
        ("watch", "AAPL", "--count", "-1"),
        ("screen", "AAPL", "--top", "0"),
        ("discover", "--top", "0"),
        ("discover", "--min-overlap", "0"),
        ("rebalance", "p.csv", "--cash", "-5"),
        ("rebalance", "p.csv", "--cash", "nan"),
    ],
)
def test_out_of_range_options_are_usage_errors(args, fake_market):
    # If an option slipped through, `watch` would loop forever and `screen`
    # would run: stop the loop at its first sleep instead of hanging
    Path("p.csv").write_text("ticker,shares\nAAPL,10\n", encoding="utf-8")
    with patch("src.cli.analyze.time.sleep", side_effect=KeyboardInterrupt):
        result = _run(*args)
    _clean_exit(result, 2)


def test_nested_output_dir_is_created(fake_market, tmp_path):
    out = tmp_path / "runs" / "2026"
    result = _run("--output-dir", str(out), "report", "AAPL")
    assert result.exit_code == 0, result.output
    assert (out / "AAPL" / "reports" / "report.md").exists()


def test_empty_journal_json_is_an_empty_list(tmp_path):
    journal = str(tmp_path / "j.toml")
    for command in ("ls", "lookback"):
        result = _run(
            "--output-dir", str(tmp_path), "journal", "--journal", journal, command, "--json"
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == []


# ==================== One watchlist path ====================


def test_global_watchlist_reaches_every_command(fake_market, tmp_path, monkeypatch):
    other = tmp_path / "lists" / "other.toml"
    other.parent.mkdir()
    base = ["--output-dir", str(tmp_path), "--watchlist", str(other)]

    result = _run(*base, "watchlist", "add", "AAPL", "--thesis", "From the other list")
    assert result.exit_code == 0, result.output
    assert set(load_watchlist(other)) == {"AAPL"}
    assert not Path("watchlist.toml").exists()

    # screen: the watchlist universe and --add-to-watchlist
    result = _run(*base, "screen", "watchlist", "MSFT", "--no-save", "--add-to-watchlist", "2")
    assert result.exit_code == 0, result.output
    assert set(load_watchlist(other)) == {"AAPL", "MSFT"}

    # journal add takes the thesis from it
    journal = str(tmp_path / "j.toml")
    result = _run(*base, "journal", "--journal", journal, "add", "AAPL")
    assert result.exit_code == 0, result.output
    assert "From the other list" in Path(journal).read_text(encoding="utf-8")

    # watchlist --file still overrides it
    result = _run(*base, "watchlist", "--file", str(tmp_path / "third.toml"), "add", "NVDA")
    assert result.exit_code == 0, result.output
    assert "NVDA" not in load_watchlist(other)


def test_rebalance_candidates_read_the_global_watchlist(tmp_path):
    from src.cli.portfolio import _candidate_tickers

    path = tmp_path / "w.toml"
    add_to_watchlist(path, ["EQNR.OL", "AAPL"])
    assert _candidate_tickers("watchlist,MSFT,aapl", path) == ["EQNR.OL", "AAPL", "MSFT"]


def test_backtest_watchlist_universe_reads_the_global_watchlist(tmp_path):
    path = tmp_path / "w.toml"
    add_to_watchlist(path, ["AAPL"])
    with patch("src.backtest.run_backtest", side_effect=RuntimeError("stop here")) as run:
        _run("--watchlist", str(path), "backtest", "watchlist", "--json")
    assert run.call_args.args[0] == ["AAPL"]


# ==================== Helpers ====================


def test_stage_progress_closes_open_bars_on_error():
    from src.cli.common import stage_progress

    closed = []

    class Bar:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(True)

        def update(self, n):
            pass

    with (
        patch("src.cli.common.click.progressbar", Bar),
        pytest.raises(RuntimeError),
        stage_progress({"rank": "Ranking"}) as progress,
    ):
        progress("rank", 1, 3)
        raise RuntimeError("fetch failed")
    assert closed == [True]


def test_cli_sources_have_no_raw_backspace_bytes():
    for path in (REPO / "src" / "cli").glob("*.py"):
        assert b"\x08" not in path.read_bytes(), path.name


def test_default_paths_come_from_one_module():
    from src import paths
    from src.portfolio.targets import DEFAULT_TARGETS
    from src.tracking import DEFAULT_JOURNAL, DEFAULT_WATCHLIST

    assert DEFAULT_WATCHLIST == paths.WATCHLIST
    assert DEFAULT_JOURNAL == paths.JOURNAL
    assert Path(paths.TARGETS) == DEFAULT_TARGETS
