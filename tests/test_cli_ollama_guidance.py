"""Docker-only guidance when Ollama preflight fails on ask/chat."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from urllib.parse import urlparse

from dockai.cli import app
from dockai.config import Settings
from dockai.formatting import OLLAMA_UNAVAILABLE_DOCKER_MARKER
from dockai.llm.ollama import OllamaNotFoundError
from dockai.llm.resolve_host import is_loopback_ollama_host


def _ollama_host_in_error_message(settings: Settings) -> str:
    host = settings.ollama_host.rstrip("/")
    if is_loopback_ollama_host(host):
        parsed = urlparse(host)
        port = parsed.port or 11434
        return f"http://localhost:{port}"
    return host


def _ollama_not_found_error(settings: Settings) -> OllamaNotFoundError:
    base = _ollama_host_in_error_message(settings)
    return OllamaNotFoundError(
        f"Ollama not found at {base}. Is it running and is the URL correct?"
    )


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        config_path=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_ask_ollama_unreachable_shows_docker_alternatives():
    settings = _settings()
    err = _ollama_not_found_error(settings)

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch(
            "dockai.cli._prepare_ollama_settings",
            side_effect=err,
        ),
    ):
        result = CliRunner().invoke(app, ["ask", "hello"])

    assert result.exit_code == 1
    assert OLLAMA_UNAVAILABLE_DOCKER_MARKER in result.output
    assert "Docker" in result.output
    lowered = result.output.lower()
    assert "containers" in lowered or "logs" in lowered
    assert "Traceback" not in result.output


def test_chat_ollama_unreachable_no_traceback():
    settings = _settings()
    err = _ollama_not_found_error(settings)

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch(
            "dockai.cli._prepare_ollama_settings",
            side_effect=err,
        ),
    ):
        result = CliRunner().invoke(app, ["chat"])

    assert result.exit_code == 1
    assert OLLAMA_UNAVAILABLE_DOCKER_MARKER in result.output
    assert "Traceback" not in result.output


def test_ask_troubleshoot_prompt_suggests_logs_for_named_container():
    settings = _settings()
    err = _ollama_not_found_error(settings)

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._can_skip_ollama_preflight", return_value=False),
        patch(
            "dockai.cli._prepare_ollama_settings",
            side_effect=err,
        ),
    ):
        result = CliRunner().invoke(
            app,
            ["ask", "why is my api restarting"],
        )

    assert result.exit_code == 1
    assert "dockai logs api" in result.output
