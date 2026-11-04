"""Ollama health preflight on ask/chat entry (not inside run_agent)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from dockai.agent import AgentResult
from dockai.cli import app
from dockai.config import Settings
from dockai.llm.ollama import (
    OllamaNotFoundError,
    assert_ollama_reachable,
    list_ollama_models,
)


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        ollama_timeout=120.0,
        ollama_health_timeout=10.0,
        config_path=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_assert_ollama_reachable_ok():
    with patch(
        "dockai.llm.ollama.list_ollama_models",
        return_value=["qwen2.5:3b"],
    ) as listed:
        assert_ollama_reachable("http://10.0.0.5:11434", health_timeout=10.0)
    listed.assert_called_once_with(
        "http://10.0.0.5:11434",
        timeout=10.0,
        preflight=True,
    )


def test_assert_ollama_reachable_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    transport = httpx.MockTransport(handler)
    with pytest.raises(OllamaNotFoundError) as exc_info:
        list_ollama_models(
            "http://203.0.113.99:11434",
            client=httpx.Client(
                base_url="http://203.0.113.99:11434",
                transport=transport,
            ),
            timeout=10.0,
            preflight=True,
        )
    msg = str(exc_info.value)
    assert "203.0.113.99" in msg
    assert "firewall" in msg.lower() or "vpn" in msg.lower()


def test_run_ask_preflight_before_agent():
    settings = _settings()
    prepare = MagicMock(side_effect=lambda s, model=None: s)
    empty = AgentResult(answer="ok", presentation=None, timings=[])

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._can_skip_ollama_preflight", return_value=False),
        patch("dockai.cli._prepare_ollama_settings", prepare),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.run_agent", return_value=empty) as agent,
        patch("dockai.cli.OllamaProvider") as provider_cls,
    ):
        provider_cls.return_value.close = MagicMock()
        result = CliRunner().invoke(app, ["ask", "explain my cluster"])

    assert result.exit_code == 0
    prepare.assert_called_once()
    agent.assert_called_once()


def test_run_ask_preflight_skipped_when_unreachable_but_shortcut():
    settings = _settings()
    prepare = MagicMock(side_effect=OllamaNotFoundError("would fail"))
    presentation = {"kind": "containers", "rows": [], "title": "x"}
    empty = AgentResult(
        answer="",
        presentation=presentation,
        timings=[("shortcut:list", 0.01)],
    )

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", prepare),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.run_agent", return_value=empty),
        patch("dockai.cli.OllamaProvider") as provider_cls,
    ):
        provider_cls.return_value.close = MagicMock()
        result = CliRunner().invoke(app, ["ask", "show running containers"])

    assert result.exit_code == 0
    prepare.assert_not_called()


def test_chat_session_health_once():
    settings = _settings()
    prepare = MagicMock(return_value=settings)
    empty = AgentResult(answer="ok", presentation=None, timings=[])

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", prepare),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.ChatSession") as session_cls,
        patch("dockai.cli.OllamaProvider") as provider_cls,
    ):
        provider_cls.return_value.close = MagicMock()
        session = MagicMock()
        session.ask.return_value = empty
        session.focus_container = None
        session_cls.return_value = session
        result = CliRunner().invoke(
            app,
            ["chat"],
            input="show running containers\nexit\n",
        )

    assert result.exit_code == 0
    assert prepare.call_count == 1
    assert session.ask.call_count == 1


def test_shortcut_still_skips_llm():
    """Regression: shortcut path must not call Ollama chat (agent test contract)."""
    from dockai.agent.loop import run_agent
    from tests.conftest import make_container

    client = MagicMock()
    client.containers.list.return_value = [
        make_container(name="pg_tileserv", logs=b"ok\n")
    ]

    class _ScriptedLLM:
        def chat(self, *_a, **_k):
            raise AssertionError("LLM must not be called for logs shortcut")

    result = run_agent(
        "show me logs for pg_tileserv",
        llm=_ScriptedLLM(),  # type: ignore[arg-type]
        client=client,
    )
    assert any(label == "shortcut:logs" for label, _ in result.timings)
