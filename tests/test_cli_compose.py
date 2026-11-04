"""CLI: `dockai compose` and `dockai .` compose context."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dockai.cli import app
from dockai.compose_context import ComposeProjectStatus, ComposeServiceStatus
from dockai.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        config_path=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_compose_cmd_success_shows_running_counts(tmp_path: Path, monkeypatch):
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        "name: demo\nservices:\n  web:\n    image: nginx\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    status = ComposeProjectStatus(
        compose_file=compose,
        project_name="demo",
        services=(
            ComposeServiceStatus(name="web", state="running", container_name="demo-web-1"),
        ),
    )

    with (
        patch("dockai.cli._ctx_settings", return_value=_settings()),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.build_compose_project_status", return_value=status),
        patch("dockai.cli._offer_compose_start") as offer,
    ):
        result = CliRunner().invoke(app, ["compose", "."])

    assert result.exit_code == 0
    assert "1/1" in result.output
    assert "demo" in result.output
    offer.assert_called_once()


def test_compose_cmd_fails_without_compose_file(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("dockai.cli._ctx_settings", return_value=_settings()):
        result = CliRunner().invoke(app, ["compose", "."])

    assert result.exit_code == 1
    assert "No Compose file" in result.output


def test_dot_entry_runs_compose(tmp_path: Path, monkeypatch):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  api:\n    image: nginx\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    status = ComposeProjectStatus(
        compose_file=compose,
        project_name="mydir",
        services=(
            ComposeServiceStatus(name="api", state="missing"),
        ),
    )

    with (
        patch("dockai.cli._ctx_settings", return_value=_settings()),
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.build_compose_project_status", return_value=status),
        patch("dockai.cli._offer_compose_start"),
    ):
        # CliRunner invokes Typer directly; `dockai .` is rewritten in main_cli.
        result = CliRunner().invoke(app, ["compose", "."])

    assert result.exit_code == 0
    assert "0/1" in result.output
