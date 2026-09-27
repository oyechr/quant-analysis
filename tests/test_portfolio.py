"""
Tests for the Nordnet holdings import. The exports here are synthetic (made-up
names and numbers) in Nordnet's format: UTF-16, tab-separated, decimal commas.
"""

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import cli
from src.portfolio import (
    PORTFOLIO_COLUMNS,
    combine_holdings,
    load_ticker_map,
    read_nordnet_holdings,
)

HEADER = (
    "Navn\tValuta\tAntall\tGAV\tI dag %\tSiste kurs\tBelåningsverdi\tVerdi\tVerdi NOK"
    "\tAvkast. %\tAvkast. NOK"
)


def _export(tmp_path, account, rows):
    path = tmp_path / f"aksjelister_konto-{account}_1.1.2026.csv"
    lines = [HEADER] + ["\t".join(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-16")
    return path


@pytest.fixture
def exports(tmp_path):
    first = _export(
        tmp_path,
        "11110000",
        [
            [
                "Example Energy",
                "NOK",
                "350",
                "31,3429",
                "0",
                "51,1",
                "0",
                "17885",
                "17885",
                "1",
                "1",
            ],
            [
                "Sample Bank",
                "NOK",
                "24",
                "213,2583",
                "0",
                "220,4",
                "0",
                "5289,6",
                "5289,6",
                "1",
                "1",
            ],
        ],
    )
    second = _export(
        tmp_path,
        "22220000",
        [
            ["Test Corp", "USD", "12", "83,1833", "0", "71,14", "0", "853,68", "8107,89", "1", "1"],
            ["Sample Bank", "NOK", "5", "1 198,56", "0", "220,4", "0", "1102", "1102", "1", "1"],
        ],
    )
    return first, second


def test_reads_nordnet_export(exports):
    holdings = read_nordnet_holdings(exports[0])

    assert list(holdings["name"]) == ["Example Energy", "Sample Bank"]
    assert holdings.loc[0, "shares"] == 350
    assert holdings.loc[0, "cost_basis"] == pytest.approx(31.3429)
    assert set(holdings["account"]) == {"11110000"}  # from the file name


def test_thousands_separator_and_label(exports):
    holdings = read_nordnet_holdings(exports[1], account="AF")
    assert holdings.loc[1, "cost_basis"] == pytest.approx(1198.56)
    assert set(holdings["account"]) == {"AF"}


def test_combines_accounts_and_reports_unmapped(exports):
    ticker_map = {"Example Energy": "EXE.OL", "Sample Bank": "SMB.OL"}

    holdings, unmapped = combine_holdings([(p, None) for p in exports], ticker_map)

    assert list(holdings.columns) == PORTFOLIO_COLUMNS
    assert len(holdings) == 4  # the same instrument in two accounts stays two rows
    assert (holdings["ticker"] == "SMB.OL").sum() == 2
    assert unmapped == ["Test Corp"]


def test_rejects_other_files(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("a\tb\n1\t2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a Nordnet holdings export"):
        read_nordnet_holdings(path)


def test_ticker_map_file(tmp_path):
    path = tmp_path / "tickers.csv"
    path.write_text("name,ticker\nExample Energy,exe.ol\nNo Ticker,\n", encoding="utf-8")
    assert load_ticker_map(path) == {"Example Energy": "EXE.OL"}
    assert load_ticker_map(tmp_path / "missing.csv") == {}


def test_cli_import(exports, tmp_path):
    ticker_map = tmp_path / "tickers.csv"
    ticker_map.write_text("name,ticker\nExample Energy,EXE.OL\n", encoding="utf-8")
    out = tmp_path / "portfolio" / "portfolio.csv"

    result = CliRunner().invoke(
        cli,
        [
            "import-portfolio",
            *map(str, exports),
            "--map",
            str(ticker_map),
            "--out",
            str(out),
            "--label",
            "11110000=ASK",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Wrote 4 holdings from 2 account(s)" in result.output
    assert "Test Corp" in result.output  # unmapped
    written = pd.read_csv(out)
    assert set(written["account"].astype(str)) == {"ASK", "22220000"}
