"""Chat session welcome hints (discoverability)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dockai.agent import AgentResult
from dockai.cli import app
from dockai.config import Settings
from dockai.formatting import CHAT_WELCOME_HINT_MARKER


def _base_settings(**overrides: object) -> Settings:
    defaults = dict(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        config_path=None,
        chat_hints=True,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_chat_shows_hints_by_default():
    settings = _base_settings()

    def fake_prepare(_settings, model=None):
        return settings

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", side_effect=fake_prepare),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.OllamaProvider") as provider_cls,
        patch("dockai.cli.typer.confirm", return_value=True),
        patch("dockai.cli.ChatSession"),
    ):
        provider_cls.return_value.close = MagicMock()
        result = CliRunner().invoke(app, ["chat"], input="exit\n")

    assert result.exit_code == 0
    assert "containers" in result.output.lower() or "logs" in result.output.lower()
    assert CHAT_WELCOME_HINT_MARKER in result.output


def test_chat_hints_disabled():
    settings = _base_settings(chat_hints=False)

    def fake_prepare(_settings, model=None):
        return settings

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", side_effect=fake_prepare),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.OllamaProvider") as provider_cls,
        patch("dockai.cli.typer.confirm", return_value=True),
        patch("dockai.cli.ChatSession"),
    ):
        provider_cls.return_value.close = MagicMock()
        result = CliRunner().invoke(app, ["chat"], input="exit\n")

    assert result.exit_code == 0
    assert CHAT_WELCOME_HINT_MARKER not in result.output


def test_ask_does_not_print_chat_hints():
    settings = _base_settings()

    def fake_prepare(_settings, model=None):
        return settings

    empty_result = AgentResult(answer="ok", presentation=None, timings=[])

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", side_effect=fake_prepare),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.run_agent", return_value=empty_result),
        patch("dockai.cli.OllamaProvider") as provider_cls,
    ):
        provider_cls.return_value.close = MagicMock()
        result = CliRunner().invoke(app, ["ask", "show running containers"])

    assert result.exit_code == 0
    assert CHAT_WELCOME_HINT_MARKER not in result.output
