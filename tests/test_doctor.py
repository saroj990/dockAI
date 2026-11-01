"""`dockai doctor` readiness checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dockai.cli import app
from dockai.config import Settings
from dockai.errors import DockerUnavailableError
from dockai.llm.ollama import OllamaNotFoundError
from dockai.llm.resolve_host import ResolvedOllamaHost


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        config_path=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_doctor_all_ok():
    settings = _settings()
    resolved = ResolvedOllamaHost(
        host="http://127.0.0.1:11434",
        configured_host="http://127.0.0.1:11434",
        used_fallback=False,
    )
    client = MagicMock()

    with (
        patch("dockai.doctor.get_client", return_value=client),
        patch("dockai.doctor.resolve_ollama_host", return_value=resolved),
        patch("dockai.cli._ctx_settings", return_value=settings),
    ):
        result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Docker: OK" in result.output
    assert "Ollama: OK" in result.output
    assert "qwen2.5:3b" in result.output


def test_doctor_docker_fails():
    settings = _settings()

    with (
        patch(
            "dockai.doctor.get_client",
            side_effect=DockerUnavailableError(
                "Docker is not running.", kind="connection_refused"
            ),
        ),
        patch("dockai.cli._ctx_settings", return_value=settings),
    ):
        result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "Docker is not running" in result.output


def test_doctor_model_missing():
    settings = _settings()
    client = MagicMock()

    with (
        patch("dockai.doctor.get_client", return_value=client),
        patch(
            "dockai.doctor.resolve_ollama_host",
            side_effect=OllamaNotFoundError(
                "Model `qwen2.5:3b` is not available on http://127.0.0.1:11434."
            ),
        ),
        patch("dockai.cli._ctx_settings", return_value=settings),
    ):
        result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "ollama pull" in result.output.lower() or "setup config" in result.output


def test_doctor_skips_ollama_when_not_required():
    settings = _settings()
    client = MagicMock()

    with (
        patch("dockai.doctor.get_client", return_value=client),
        patch("dockai.doctor.resolve_ollama_host") as resolve,
        patch("dockai.cli._ctx_settings", return_value=settings),
    ):
        result = CliRunner().invoke(app, ["doctor", "--no-require-ollama"])

    assert result.exit_code == 0
    resolve.assert_not_called()
    assert "skipped" in result.output.lower()
