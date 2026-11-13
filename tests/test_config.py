"""Tests for where config.json is found, keys from the environment, and
keeping keys out of the config's repr."""

import json
from pathlib import Path

import pytest

from src import config as config_module
from src.config import AnalysisConfig, config_path, get_config, with_env_keys

ENV_VARS = [var for names in config_module.ENV_KEYS.values() for var in names]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout at tmp_path/repo, run from tmp_path/elsewhere, with no
    QUANT_CONFIG or key variables from the real environment."""
    root = tmp_path / "repo"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(config_module, "REPO_ROOT", root)
    monkeypatch.chdir(elsewhere)
    for var in ["QUANT_CONFIG", *ENV_VARS]:
        monkeypatch.delenv(var, raising=False)
    return root


def test_config_is_found_from_another_folder(repo: Path) -> None:
    """Run from a subfolder, the keys and TTLs used to drop to defaults silently."""
    assert config_path() == repo / "config.json"


def test_a_local_config_comes_first(repo: Path) -> None:
    Path("config.json").write_text("{}", encoding="utf-8")
    assert config_path() == Path("config.json")


def test_quant_config_overrides_both(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Path("config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("QUANT_CONFIG", "D:/elsewhere/quant.json")
    assert config_path() == Path("D:/elsewhere/quant.json")


def test_get_config_loads_the_checkouts_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "config.json").write_text(
        json.dumps({"risk_free_rate": 0.05, "edgar_user_agent": "Me me@example.com"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "_default_config", None)
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")

    config = get_config()

    assert config.risk_free_rate == 0.05
    assert config.edgar_user_agent == "Me me@example.com"
    assert config.llm_google_api_key == "from-env"


def test_environment_fills_missing_keys_only() -> None:
    config = AnalysisConfig(llm_anthropic_api_key="from-file")
    env = {"ANTHROPIC_API_KEY": "from-env", "OPENAI_API_KEY": "oa", "OPENFIGI_API_KEY": "figi"}

    with_env_keys(config, env)

    assert config.llm_anthropic_api_key == "from-file"
    assert config.llm_openai_api_key == "oa"
    assert config.openfigi_api_key == "figi"
    assert config.llm_google_api_key is None


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"GEMINI_API_KEY": "g1", "GOOGLE_API_KEY": "g2"}, "g1"),
        ({"GOOGLE_API_KEY": "g2"}, "g2"),
        ({"GEMINI_API_KEY": ""}, None),
    ],
)
def test_google_key_from_either_variable(env: dict[str, str], expected: object) -> None:
    assert with_env_keys(AnalysisConfig(), env).llm_google_api_key == expected


def test_repr_hides_api_keys() -> None:
    """A logged or printed config used to show every key in full."""
    config = AnalysisConfig(
        llm_anthropic_api_key="secret-a",
        llm_openai_api_key="secret-o",
        llm_google_api_key="secret-g",
        openfigi_api_key="secret-f",
    )
    assert "secret" not in repr(config)
