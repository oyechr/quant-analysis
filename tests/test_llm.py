"""Tests for the chat LLM layer (src/llm.py): routing, errors and stop reasons.

The provider SDKs are replaced by fakes; the errors are the SDKs' own classes.
"""

from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional

import anthropic
import httpx2
import openai
import pytest

from src import llm

MESSAGES = [{"role": "user", "content": "Bear case?"}]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAnthropicStream:
    def __init__(self, texts: List[str], stop_reason: str, error: Optional[Exception]):
        self._texts = texts
        self._stop_reason = stop_reason
        self._error = error

    def __enter__(self) -> "_FakeAnthropicStream":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    @property
    def text_stream(self) -> Iterator[str]:
        yield from self._texts
        if self._error is not None:
            raise self._error

    def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(stop_reason=self._stop_reason)


def _fake_anthropic(
    monkeypatch: pytest.MonkeyPatch,
    texts: List[str] = ["Fine."],
    stop_reason: str = "end_turn",
    error: Optional[Exception] = None,
    open_error: Optional[Exception] = None,
) -> None:
    def _stream(**kwargs: Any) -> _FakeAnthropicStream:
        if open_error is not None:
            raise open_error
        return _FakeAnthropicStream(texts, stop_reason, error)

    client = SimpleNamespace(messages=SimpleNamespace(stream=_stream))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)


def _chunk(text: Optional[str], finish_reason: Optional[str] = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    chunks: List[SimpleNamespace],
    error: Optional[Exception] = None,
) -> Dict[str, Any]:
    """Record the create() kwargs."""
    seen: Dict[str, Any] = {}

    def _create(**kwargs: Any) -> Iterator[SimpleNamespace]:
        seen["create"] = kwargs
        if error is not None:
            raise error
        return iter(chunks)

    def _client(api_key: str) -> SimpleNamespace:
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))

    monkeypatch.setattr(openai, "OpenAI", _client)
    return seen


_A_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _anthropic_status(cls: Any, status: int, body: Any = None) -> Exception:
    return cls("error", response=httpx2.Response(status, request=_A_REQUEST), body=body)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model, provider",
    [
        ("claude-haiku-5-5", "anthropic"),
        ("Claude-Opus-5-5", "anthropic"),
        ("gpt-4.1", "openai"),
        ("o4-mini", "openai"),
        ("Meta-Llama-3.3-70B", "openai"),
    ],
)
def test_only_claude_models_go_to_anthropic(model: str, provider: str) -> None:
    assert llm._infer_provider(model) == provider


def test_non_claude_model_without_openai_key_is_a_config_error() -> None:
    """A non-Claude name used to go to Anthropic and ask for an Anthropic key."""
    with pytest.raises(llm.LLMConfigError, match="llm_openai_api_key"):
        llm.chat_turn("ctx", MESSAGES, model="Meta-Llama-3.3-70B")


def test_default_model_is_claude_haiku() -> None:
    """The old default, gpt-4.1 through GitHub Models, was retired on 2026-07-30."""
    with pytest.raises(llm.LLMConfigError, match="llm_anthropic_api_key"):
        llm.chat_turn("ctx", MESSAGES)


def test_claude_without_key_is_a_config_error() -> None:
    with pytest.raises(llm.LLMConfigError, match="llm_anthropic_api_key"):
        llm.chat_turn("ctx", MESSAGES, model="claude-haiku-5-5")


# ---------------------------------------------------------------------------
# OpenAI token limits and stop reasons
# ---------------------------------------------------------------------------


def test_openai_uses_max_completion_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """o-series models reject max_tokens; OpenAI accepts max_completion_tokens for all."""
    seen = _fake_openai(monkeypatch, [_chunk("Hi.", "stop")])
    llm._chat_openai("sys", MESSAGES, "o4-mini", api_key="k")
    assert "max_tokens" not in seen["create"]
    assert seen["create"]["max_completion_tokens"] == llm.OPENAI_MAX_TOKENS


def test_openai_truncated_reply_is_noted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_openai(monkeypatch, [_chunk("Half a"), _chunk(None, "length")])
    assert llm._chat_openai("sys", MESSAGES, "gpt-4.1", api_key="k") == "Half a"
    assert "cut off" in capsys.readouterr().out


def test_openai_rate_limit_becomes_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx2.Response(429, request=httpx2.Request("POST", "https://api.openai.com"))
    error = openai.RateLimitError("slow down", response=response, body=None)
    _fake_openai(monkeypatch, [], error=error)
    with pytest.raises(ValueError, match="quota"):
        llm._chat_openai("sys", MESSAGES, "gpt-4.1", api_key="k")


# ---------------------------------------------------------------------------
# Anthropic errors and stop reasons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error, message",
    [
        (_anthropic_status(anthropic.RateLimitError, 429), "rate limit"),
        (_anthropic_status(anthropic.OverloadedError, 529), "overloaded"),
        (_anthropic_status(anthropic.InternalServerError, 500), "server error"),
        (_anthropic_status(anthropic.AuthenticationError, 401), "llm_anthropic_api_key"),
        (_anthropic_status(anthropic.NotFoundError, 404), "no model 'claude-haiku-5-5'"),
        (anthropic.APIConnectionError(request=_A_REQUEST), "network"),
        (anthropic.APITimeoutError(request=_A_REQUEST), "in time"),
    ],
)
def test_anthropic_errors_become_value_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    """These used to escape as SDK exceptions and end the chat with a traceback."""
    _fake_anthropic(monkeypatch, open_error=error)
    with pytest.raises(ValueError, match=message):
        llm._chat_anthropic("sys", MESSAGES, "claude-haiku-5-5", "key")


def test_anthropic_error_mid_stream_is_read_from_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error event inside a stream carries the stream's 200 status."""
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    error = _anthropic_status(anthropic.APIStatusError, 200, body)
    _fake_anthropic(monkeypatch, texts=["Part"], error=error)
    with pytest.raises(ValueError, match="overloaded"):
        llm._chat_anthropic("sys", MESSAGES, "claude-haiku-5-5", "key")


def test_anthropic_refusal_is_noted_and_returns_the_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_anthropic(monkeypatch, texts=[], stop_reason="refusal")
    assert llm._chat_anthropic("sys", MESSAGES, "claude-haiku-5-5", "key") == ""
    assert "declined" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The chat loop keeps its history
# ---------------------------------------------------------------------------


def _write_report(tmp_path: Any) -> None:
    import json

    from tests.test_cli import _mock_report_data

    report_dir = tmp_path / "AAPL" / "reports"
    report_dir.mkdir(parents=True)
    (report_dir / "full_report.json").write_text(
        json.dumps(_mock_report_data("AAPL")), encoding="utf-8"
    )


def _run_chat(tmp_path: Any, replies: List[Any], typed: str, intro: bool = False) -> List[Any]:
    """Run `quant chat AAPL`; each reply is a string or an exception to raise."""
    from unittest.mock import patch

    from click.testing import CliRunner

    from src.cli import cli

    calls: List[Any] = []
    queue = list(replies)

    def _turn(context: str, messages: List[Dict[str, str]], model: Any = None) -> str:
        calls.append([dict(m) for m in messages])
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return str(reply)

    args = ["--output-dir", str(tmp_path), "chat", "AAPL"] + ([] if intro else ["--no-intro"])
    with patch("src.llm.chat_turn", side_effect=_turn):
        result = CliRunner().invoke(cli, args, input=typed, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return calls


def test_chat_survives_an_api_error_and_keeps_history(tmp_path: Any) -> None:
    _write_report(tmp_path)
    calls = _run_chat(
        tmp_path,
        ["Answer one.", ValueError("Anthropic is overloaded"), "Answer three."],
        "Q1\nQ2\nQ3\n/quit\n",
    )
    assert len(calls) == 3
    assert [m["content"] for m in calls[2]] == ["Q1", "Answer one.", "Q3"]


def test_chat_does_not_keep_an_empty_reply(tmp_path: Any) -> None:
    """An empty assistant turn makes the next request fail with a 400."""
    _write_report(tmp_path)
    calls = _run_chat(tmp_path, ["", "Answer."], "Q1\nQ2\n/quit\n")
    assert [m["content"] for m in calls[1]] == ["Q2"]
    assert all(m["content"] for call in calls for m in call)


def test_chat_intro_failure_does_not_end_the_session(tmp_path: Any) -> None:
    _write_report(tmp_path)
    calls = _run_chat(tmp_path, [ValueError("overloaded"), "Answer."], "Q1\n/quit\n", intro=True)
    assert [m["content"] for m in calls[1]] == ["Q1"]


def test_chat_intro_without_credentials_exits(tmp_path: Any) -> None:
    from click.testing import CliRunner

    from src.cli import cli

    _write_report(tmp_path)
    result = CliRunner().invoke(
        cli, ["--output-dir", str(tmp_path), "chat", "AAPL", "--model", "claude-haiku-5-5"]
    )
    assert result.exit_code == 1
    assert "llm_anthropic_api_key" in result.output


def test_openai_empty_reply_says_what_came_back(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_openai(monkeypatch, [])
    assert llm._chat_openai("sys", MESSAGES, "gpt-4.1", api_key="k") == ""
    assert "sent no text (0 stream chunks, finish reason none)" in capsys.readouterr().out


def test_openai_refusal_is_shown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    chunk = _chunk(None, "stop")
    chunk.choices[0].delta.refusal = "I can't help with that."
    _fake_openai(monkeypatch, [chunk])
    assert llm._chat_openai("sys", MESSAGES, "gpt-4.1", api_key="k") == ""
    assert "declined: I can't help with that." in capsys.readouterr().out
