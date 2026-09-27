"""
Tests for the CLI interface.
Uses Click's CliRunner for integration testing with mocked data fetching.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cli import cli
from src.pipeline import AnalysisBundle
from src.scoring import ScoringConfig
from src.scoring.scorer import ScoringResult


def _mock_scoring_result(ticker: str = "AAPL") -> ScoringResult:
    """Create a minimal ScoringResult for testing."""
    return ScoringResult(
        ticker=ticker,
        composite_score=72.5,
        signal="Buy",
        confidence="High",
        confidence_score=0.85,
        strengths=["Strong momentum"],
        concerns=["High valuation"],
        generated_at="2025-01-01T00:00:00",
        dimensions_available=4,
        dimensions_total=4,
    )


def _mock_report_data(ticker: str = "AAPL") -> dict:
    """Create minimal report data for testing."""
    return {
        "ticker": ticker,
        "info": {"trailingPE": 28.5, "marketCap": 3000000000000},
        "scoring": {"composite_score": 72.5},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "risk_analysis": {},
        "valuation_analysis": {},
    }


def _mock_bundle(ticker: str = "AAPL") -> AnalysisBundle:
    """Create a minimal AnalysisBundle as returned by ReportGenerator.generate()."""
    return AnalysisBundle(
        ticker=ticker,
        report=_mock_report_data(ticker),
        scoring=_mock_scoring_result(ticker),
    )


class TestCLIGroup:
    """Test the root CLI group."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Quantitative stock analysis tool" in result.output

    def test_subcommands_listed(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "report" in result.output
        assert "score" in result.output
        assert "compare" in result.output
        assert "watch" in result.output
        assert "chat" in result.output


class TestReportCommand:
    """Test the 'report' subcommand."""

    @patch("src.cli.ReportGenerator")
    def test_report_basic(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _mock_bundle()
        mock_gen_cls.return_value = mock_gen

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "AAPL"])
        assert result.exit_code == 0
        assert "AAPL" in result.output
        mock_gen.generate.assert_called_once()

    @patch("src.cli.ReportGenerator")
    def test_report_with_options(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _mock_bundle("TSLA")
        mock_gen_cls.return_value = mock_gen

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--period",
                "2y",
                "--no-cache",
                "--format",
                "json",
                "report",
                "TSLA",
                "--exclude-technical",
                "--config",
                "value",
            ],
        )
        assert result.exit_code == 0
        options = mock_gen.generate.call_args[0][1]
        assert options.period == "2y"
        assert options.use_cache is False
        assert options.include_technical is False
        assert options.scoring_config.weights == ScoringConfig.value_investor().weights
        assert mock_gen.generate.call_args[1]["output_format"] == "json"

    @patch("src.cli.ReportGenerator")
    def test_report_prints_freshness_warnings(self, mock_gen_cls):
        bundle = _mock_bundle()
        bundle.report["data_freshness"] = {"warnings": ["Latest price bar is 9 days old"]}
        mock_gen_cls.return_value = MagicMock(generate=MagicMock(return_value=bundle))

        result = CliRunner().invoke(cli, ["report", "AAPL"])

        assert "Latest price bar is 9 days old" in result.output

    def test_report_missing_ticker(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["report"])
        assert result.exit_code != 0


class TestScoreCommand:
    """Test the 'score' subcommand."""

    @patch("src.cli.ReportGenerator")
    def test_score_single(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _mock_bundle()
        mock_gen_cls.return_value = mock_gen

        runner = CliRunner()
        result = runner.invoke(cli, ["score", "AAPL"])
        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "STOCK SCORES" in result.output

    @patch("src.cli.ReportGenerator")
    def test_score_multiple_keeps_input_order(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = lambda ticker, *a, **kw: _mock_bundle(ticker)
        mock_gen_cls.return_value = mock_gen

        result = CliRunner().invoke(cli, ["score", "MSFT", "AAPL", "--workers", "2"])

        assert result.exit_code == 0
        table = result.output.split("STOCK SCORES")[1]
        assert table.index("MSFT") < table.index("AAPL")

    @patch("src.cli.ReportGenerator")
    def test_score_reports_errors_per_ticker(self, mock_gen_cls):
        def _generate(ticker, *args, **kwargs):
            if ticker == "BAD":
                raise ValueError("No data returned for ticker BAD")
            return _mock_bundle(ticker)

        mock_gen_cls.return_value = MagicMock(generate=MagicMock(side_effect=_generate))

        result = CliRunner().invoke(cli, ["score", "AAPL", "BAD"])

        assert result.exit_code == 0
        assert "BAD" in result.output
        assert "ERROR" in result.output

    @patch("src.cli.ReportGenerator")
    def test_score_with_config(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _mock_bundle()
        mock_gen_cls.return_value = mock_gen

        runner = CliRunner()
        result = runner.invoke(cli, ["score", "AAPL", "--config", "value"])
        assert result.exit_code == 0
        options = mock_gen.generate.call_args[0][1]
        assert options.scoring_config.weights == ScoringConfig.value_investor().weights

    def test_score_missing_tickers(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["score"])
        assert result.exit_code != 0


class TestCompareCommand:
    """Test the 'compare' subcommand."""

    @patch("src.cli.TickerComparator")
    def test_compare_basic(self, mock_comp_cls):
        import pandas as pd

        mock_comp = MagicMock()
        mock_comp.side_by_side_scores.return_value = pd.DataFrame(
            {"AAPL": {"Composite Score": 72.5}, "MSFT": {"Composite Score": 68.0}}
        )
        mock_comp.relative_valuation.return_value = pd.DataFrame()
        mock_comp.key_metrics_table.return_value = pd.DataFrame()
        mock_comp.correlation_matrix.return_value = pd.DataFrame()
        mock_comp_cls.return_value = mock_comp

        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "AAPL", "MSFT"])
        assert result.exit_code == 0
        assert "Comparing" in result.output

    def test_compare_too_few_tickers(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "AAPL"])
        assert result.exit_code != 0


class TestWatchCommand:
    """Test the 'watch' subcommand."""

    @patch("src.cli.ReportGenerator")
    def test_watch_single_iteration(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _mock_bundle()
        mock_gen_cls.return_value = mock_gen

        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "AAPL", "--count", "1", "--interval", "1"])
        assert result.exit_code == 0
        assert "WATCH MODE" in result.output
        assert mock_gen.generate.call_args[1]["output_format"] == "none"

    def test_watch_missing_tickers(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["watch"])
        assert result.exit_code != 0


class TestChatCommand:
    """Test the 'chat' subcommand."""

    def test_chat_missing_ticker(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["chat"])
        assert result.exit_code != 0

    def test_chat_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "--help"])
        assert result.exit_code == 0
        assert "TICKER" in result.output
        assert "--no-intro" in result.output
        assert "--debug-context" in result.output

    @patch("src.cli.ReportGenerator")
    def test_chat_debug_context_uses_existing_report(self, mock_gen_cls, tmp_path):
        """--debug-context prints context and exits without calling the LLM."""
        report_dir = tmp_path / "AAPL" / "reports"
        report_dir.mkdir(parents=True)
        report_path = report_dir / "full_report.json"
        import json

        report_path.write_text(json.dumps(_mock_report_data("AAPL")), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--output-dir",
                str(tmp_path),
                "chat",
                "AAPL",
                "--debug-context",
            ],
        )
        assert result.exit_code == 0
        # Should print the context block and exit — no LLM call
        assert "TICKER: AAPL" in result.output
        mock_gen_cls.return_value.generate_full_report.assert_not_called()

    @patch("src.cli.ReportGenerator")
    def test_chat_generates_report_when_missing(self, mock_gen_cls, tmp_path):
        """chat auto-generates a report if none exists, then starts the session."""
        mock_gen = MagicMock()
        mock_gen.generate_full_report.return_value = _mock_report_data("MSFT")
        mock_gen_cls.return_value = mock_gen

        # Patch chat_turn so we never hit the LLM; simulate user typing /quit
        with patch("src.llm.chat_turn", return_value="Brief here."):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--output-dir", str(tmp_path), "chat", "MSFT"],
                # no-intro skips the auto-brief; /quit exits the loop
                input="/quit\n",
                catch_exceptions=False,
            )

        # Report was generated because no JSON existed
        mock_gen.generate_full_report.assert_called_once()
        # Session header should be present
        assert "MSFT" in result.output

    @patch("src.cli.ReportGenerator")
    def test_chat_loads_existing_report_without_regenerating(self, mock_gen_cls, tmp_path):
        """chat loads an existing report without re-generating it."""
        report_dir = tmp_path / "AAPL" / "reports"
        report_dir.mkdir(parents=True)
        import json

        (report_dir / "full_report.json").write_text(
            json.dumps(_mock_report_data("AAPL")), encoding="utf-8"
        )

        with patch("src.llm.chat_turn", return_value="Brief."):
            runner = CliRunner()
            runner.invoke(
                cli,
                ["--output-dir", str(tmp_path), "chat", "AAPL", "--no-intro"],
                input="/quit\n",
                catch_exceptions=False,
            )

        mock_gen_cls.return_value.generate_full_report.assert_not_called()

    @patch("src.cli.ReportGenerator")
    def test_chat_conversation_loop(self, mock_gen_cls, tmp_path):
        """Messages are accumulated and passed to chat_turn on each turn."""
        report_dir = tmp_path / "AAPL" / "reports"
        report_dir.mkdir(parents=True)
        import json

        (report_dir / "full_report.json").write_text(
            json.dumps(_mock_report_data("AAPL")), encoding="utf-8"
        )

        call_messages = []

        def _capture_turn(context, messages, model=None):
            call_messages.append(list(messages))
            return "Analyst response."

        with patch("src.llm.chat_turn", side_effect=_capture_turn):
            runner = CliRunner()
            runner.invoke(
                cli,
                ["--output-dir", str(tmp_path), "chat", "AAPL", "--no-intro"],
                input="What is the bear case?\nWhat is the bull case?\n/quit\n",
                catch_exceptions=False,
            )

        # Two user turns — each successive call should have more history
        assert len(call_messages) == 2
        assert call_messages[0][-1]["content"] == "What is the bear case?"
        assert len(call_messages[1]) > len(call_messages[0])
        assert call_messages[1][-1]["content"] == "What is the bull case?"

    @patch("src.cli.ReportGenerator")
    def test_chat_clear_resets_history(self, mock_gen_cls, tmp_path):
        """/clear resets message history but context is preserved."""
        report_dir = tmp_path / "AAPL" / "reports"
        report_dir.mkdir(parents=True)
        import json

        (report_dir / "full_report.json").write_text(
            json.dumps(_mock_report_data("AAPL")), encoding="utf-8"
        )

        call_messages = []

        def _capture_turn(context, messages, model=None):
            call_messages.append(list(messages))
            return "Response."

        with patch("src.llm.chat_turn", side_effect=_capture_turn):
            runner = CliRunner()
            runner.invoke(
                cli,
                ["--output-dir", str(tmp_path), "chat", "AAPL", "--no-intro"],
                input="First question?\n/clear\nSecond question?\n/quit\n",
                catch_exceptions=False,
            )

        # After /clear the second question should arrive with only 1 message in history
        assert len(call_messages) == 2
        assert len(call_messages[1]) == 1
        assert call_messages[1][0]["content"] == "Second question?"
