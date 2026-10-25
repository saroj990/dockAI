"""CLI messaging when Docker daemon is down."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from dockai.cli import app
from dockai.config import Settings
from dockai.errors import DockerUnavailableError


def test_chat_docker_not_running_no_traceback():
    settings = Settings(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        config_path=None,
    )

    def fake_prepare(_settings, model=None):
        return settings

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", side_effect=fake_prepare),
        patch(
            "dockai.cli.get_client",
            side_effect=DockerUnavailableError(
                "Docker is not running.", kind="connection_refused"
            ),
        ),
    ):
        result = CliRunner().invoke(app, ["chat"])

    assert result.exit_code == 1
    assert "Docker is not running" in result.output
    assert "Traceback" not in result.output
