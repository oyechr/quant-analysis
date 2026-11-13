"""Tests for utils.files: writes that never leave a truncated file, and
ticker folders that stay inside their base folder."""

import os
from pathlib import Path

import pytest

from src.data_fetcher import DataFetcher
from src.utils.files import atomic_write, atomic_write_text, ticker_dir


def test_writes_and_replaces(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "watchlist.toml"
    atomic_write_text(path, "first")
    atomic_write_text(path, "second")
    assert path.read_text(encoding="utf-8") == "second"
    assert [p.name for p in path.parent.iterdir()] == ["watchlist.toml"]  # no temp left


def test_failed_write_keeps_the_old_file(tmp_path: Path) -> None:
    path = tmp_path / "journal.toml"
    atomic_write_text(path, "precious")

    def crash(tmp: Path) -> None:
        tmp.write_text("half", encoding="utf-8")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        atomic_write(path, crash)

    assert path.read_text(encoding="utf-8") == "precious"
    assert [p.name for p in tmp_path.iterdir()] == ["journal.toml"]


def test_writers_get_their_own_temp_files(tmp_path: Path) -> None:
    seen: list[str] = []
    path = tmp_path / "scores.csv"

    def write(tmp: Path) -> None:
        seen.append(tmp.name)
        tmp.write_text("x")

    for _ in range(2):
        atomic_write(path, write)
    assert len(set(seen)) == 2


def test_replace_retries_while_windows_holds_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.utils.files as files

    calls: list[str | Path] = []
    real_replace = os.replace

    def flaky(src: str | Path, dst: str | Path) -> None:
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError("in use")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(files, "_REPLACE_WAIT_SECONDS", 0)
    atomic_write_text(tmp_path / "a.json", "{}")
    assert len(calls) == 3 and (tmp_path / "a.json").read_text() == "{}"


@pytest.mark.parametrize(
    "symbol, folder",
    [
        ("EQNR.OL", "EQNR.OL"),
        ("aapl", "AAPL"),
        ("BRK-B", "BRK-B"),
        ("^GSPC", "^GSPC"),
        ("EURUSD=X", "EURUSD=X"),
        ("M&M.NS", "M&M.NS"),
        ("CON.DE", "_CON.DE"),  # Windows device names, reserved with any extension
        ("nul", "_NUL"),
        ("COM1", "_COM1"),
        ("CONE", "CONE"),
    ],
)
def test_ticker_dir_accepts_symbols(symbol: str, folder: str) -> None:
    assert ticker_dir("data", symbol) == Path("data") / folder


@pytest.mark.parametrize(
    "bad", ["", ".", "..", "../X", r"..\X", "A/B", r"A\B", "C:", "A..B", "X.", "A B", "A" * 21]
)
def test_ticker_dir_rejects_paths(bad: str) -> None:
    with pytest.raises(ValueError, match="Not a valid ticker symbol"):
        ticker_dir("data", bad)


def test_fetcher_cache_stays_inside_its_folder(tmp_path: Path) -> None:
    """A symbol from a file or the command line used to become a folder as is."""
    fetcher = DataFetcher(cache_dir=str(tmp_path / "data"))
    with pytest.raises(ValueError, match="Not a valid ticker symbol"):
        fetcher._get_cache_file_path("../ESCAPED", "info.json")
    assert not (tmp_path / "ESCAPED").exists()
