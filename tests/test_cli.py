"""
Tests for the CLI interface.
Uses Click's CliRunner for integration testing with mocked data fetching.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cli import cli
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
        assert "analyze" in result.output
        assert "score" in result.output
        assert "compare" in result.output
        assert "watch" in result.output


class TestAnalyzeCommand:
    """Test the 'analyze' subcommand."""

    @patch("src.cli.StockScorer")
    @patch("src.cli.ReportGenerator")
    def test_analyze_basic(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.return_value = _mock_report_data()
        mock_gen_cls.return_value = mock_gen

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = _mock_scoring_result()
        mock_scorer_cls.return_value = mock_scorer

        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "AAPL"])
        assert result.exit_code == 0
        assert "AAPL" in result.output
        mock_gen.generate_full_report.assert_called_once()

    @patch("src.cli.StockScorer")
    @patch("src.cli.ReportGenerator")
    def test_analyze_with_options(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.return_value = _mock_report_data()
        mock_gen_cls.return_value = mock_gen
        mock_scorer_cls.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--period", "2y", "--no-cache", "--format", "json",
            "analyze", "TSLA", "--exclude-technical",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_gen.generate_full_report.call_args[1]
        assert call_kwargs["period"] == "2y"
        assert call_kwargs["use_cache"] is False
        assert call_kwargs["output_format"] == "json"
        assert call_kwargs["include_technical"] is False

    def test_analyze_missing_ticker(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze"])
        assert result.exit_code != 0


class TestScoreCommand:
    """Test the 'score' subcommand."""

    @patch("src.cli.StockScorer")
    @patch("src.cli.ReportGenerator")
    def test_score_single(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.return_value = _mock_report_data()
        mock_gen_cls.return_value = mock_gen

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = _mock_scoring_result()
        mock_scorer_cls.return_value = mock_scorer

        runner = CliRunner()
        result = runner.invoke(cli, ["score", "AAPL"])
        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "STOCK SCORES" in result.output

    @patch("src.cli.StockScorer")
    @patch("src.cli.ReportGenerator")
    def test_score_multiple(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.side_effect = [
            _mock_report_data("AAPL"),
            _mock_report_data("MSFT"),
        ]
        mock_gen_cls.return_value = mock_gen

        mock_scorer = MagicMock()
        mock_scorer.score.side_effect = [
            _mock_scoring_result("AAPL"),
            _mock_scoring_result("MSFT"),
        ]
        mock_scorer_cls.return_value = mock_scorer

        runner = CliRunner()
        result = runner.invoke(cli, ["score", "AAPL", "MSFT"])
        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "MSFT" in result.output

    @patch("src.cli.StockScorer")
    @patch("src.cli.ReportGenerator")
    def test_score_with_config(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.return_value = _mock_report_data()
        mock_gen_cls.return_value = mock_gen
        mock_scorer_cls.return_value = MagicMock(
            score=MagicMock(return_value=_mock_scoring_result())
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["score", "AAPL", "--config", "value"])
        assert result.exit_code == 0

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

    @patch("src.cli.StockScorer")
    @patch("src.cli.ReportGenerator")
    def test_watch_single_iteration(self, mock_gen_cls, mock_scorer_cls):
        mock_gen = MagicMock()
        mock_gen.generate_full_report.return_value = _mock_report_data()
        mock_gen_cls.return_value = mock_gen

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = _mock_scoring_result()
        mock_scorer_cls.return_value = mock_scorer

        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "AAPL", "--count", "1", "--interval", "1"])
        assert result.exit_code == 0
        assert "WATCH MODE" in result.output

    def test_watch_missing_tickers(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["watch"])
        assert result.exit_code != 0
