"""Tests for utils.files: writes that never leave a truncated file."""

import pytest

from src.utils.files import atomic_write, atomic_write_text


def test_writes_and_replaces(tmp_path):
    path = tmp_path / "sub" / "watchlist.toml"
    atomic_write_text(path, "first")
    atomic_write_text(path, "second")
    assert path.read_text(encoding="utf-8") == "second"
    assert [p.name for p in path.parent.iterdir()] == ["watchlist.toml"]  # no temp left


def test_failed_write_keeps_the_old_file(tmp_path):
    path = tmp_path / "journal.toml"
    atomic_write_text(path, "precious")

    def crash(tmp):
        tmp.write_text("half", encoding="utf-8")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        atomic_write(path, crash)

    assert path.read_text(encoding="utf-8") == "precious"
    assert [p.name for p in tmp_path.iterdir()] == ["journal.toml"]


def test_writers_get_their_own_temp_files(tmp_path, monkeypatch):
    seen = []
    path = tmp_path / "scores.csv"
    for _ in range(2):
        atomic_write(path, lambda tmp: seen.append(tmp.name) or tmp.write_text("x"))
    assert len(set(seen)) == 2


def test_replace_retries_while_windows_holds_the_file(tmp_path, monkeypatch):
    import src.utils.files as files

    calls = []
    real_replace = files.os.replace

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError("in use")
        real_replace(src, dst)

    monkeypatch.setattr(files.os, "replace", flaky)
    monkeypatch.setattr(files, "_REPLACE_WAIT_SECONDS", 0)
    atomic_write_text(tmp_path / "a.json", "{}")
    assert len(calls) == 3 and (tmp_path / "a.json").read_text() == "{}"
