"""Ollama host preflight and local fallback when remote is unreachable."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from dockai.config import DEFAULT_OLLAMA_HOST, Settings
from dockai.llm.ollama import OllamaNotFoundError
from dockai.llm.resolve_host import (
    is_loopback_ollama_host,
    resolve_ollama_host,
    settings_with_resolved_ollama,
)


def _settings(host: str, *, model: str = "qwen2.5:3b") -> Settings:
    return Settings(
        ollama_host=host,
        ollama_model=model,
        ollama_timeout=30.0,
        ollama_health_timeout=5.0,
        ollama_fallback_host=None,
        docker_timeout=60.0,
        verbose=False,
        config_path=None,
    )


def test_is_loopback_ollama_host():
    assert is_loopback_ollama_host("http://127.0.0.1:11434")
    assert is_loopback_ollama_host("http://localhost:11434")
    assert not is_loopback_ollama_host("http://10.0.0.5:11434")


def test_resolve_ollama_host_primary_ok():
    settings = _settings("http://203.0.113.99:11434")
    probes: list[str] = []

    def probe(host: str, _timeout: float) -> bool:
        probes.append(host)
        return host == "http://203.0.113.99:11434"

    with patch(
        "dockai.llm.resolve_host._model_available",
        return_value=True,
    ):
        resolved = resolve_ollama_host(settings, probe=probe)
    assert resolved.host == "http://203.0.113.99:11434"
    assert resolved.used_fallback is False
    assert probes == ["http://203.0.113.99:11434"]


def test_resolve_ollama_host_remote_fail_local_ok():
    settings = _settings("http://203.0.113.99:11434")

    def probe(host: str, _timeout: float) -> bool:
        return host.rstrip("/") == DEFAULT_OLLAMA_HOST.rstrip("/")

    with patch(
        "dockai.llm.resolve_host._model_available",
        return_value=True,
    ):
        resolved = resolve_ollama_host(settings, probe=probe)
    assert resolved.used_fallback is True
    assert resolved.host == DEFAULT_OLLAMA_HOST.rstrip("/")
    assert "unreachable" in (resolved.fallback_notice or "")


def test_resolve_ollama_host_both_fail_message():
    settings = _settings("http://203.0.113.99:11434")

    def probe(_host: str, _timeout: float) -> bool:
        return False

    with pytest.raises(OllamaNotFoundError) as exc_info:
        resolve_ollama_host(settings, probe=probe)
    msg = str(exc_info.value).lower()
    assert "debugging" in msg or "natural-language" in msg
    assert "setup config" in msg
    assert "203.0.113.99" in str(exc_info.value)


def test_no_fallback_when_primary_is_local():
    settings = _settings("http://127.0.0.1:11434")
    calls: list[str] = []

    def probe(host: str, _timeout: float) -> bool:
        calls.append(host)
        return False

    with pytest.raises(OllamaNotFoundError):
        resolve_ollama_host(settings, probe=probe)
    assert calls == ["http://127.0.0.1:11434"]


def test_settings_with_resolved_ollama_updates_host():
    settings = _settings("http://203.0.113.99:11434")

    def probe(host: str, _timeout: float) -> bool:
        return is_loopback_ollama_host(host)

    with patch(
        "dockai.llm.resolve_host._model_available",
        return_value=True,
    ):
        updated, resolved = settings_with_resolved_ollama(settings, probe=probe)
    assert updated.ollama_host == DEFAULT_OLLAMA_HOST.rstrip("/")
    assert resolved.used_fallback is True


def test_run_ask_uses_fallback_provider():
    from dockai.cli import _prepare_ollama_settings

    settings = _settings("http://203.0.113.99:11434")

    def probe(host: str, _timeout: float) -> bool:
        return is_loopback_ollama_host(host)

    with (
        patch(
            "dockai.cli.settings_with_resolved_ollama",
            side_effect=lambda s, probe=None: settings_with_resolved_ollama(
                s, probe=probe
            ),
        ),
        patch(
            "dockai.llm.resolve_host._model_available",
            return_value=True,
        ),
    ):
        cfg = _prepare_ollama_settings(settings)
    assert cfg.ollama_host == DEFAULT_OLLAMA_HOST.rstrip("/")


def test_chat_prepare_ollama_only_once_pattern():
    """Chat calls _prepare_ollama_settings once at startup (not per line)."""
    from dockai.cli import _prepare_ollama_settings

    settings = _settings("http://203.0.0.1:11434")
    with patch(
        "dockai.llm.resolve_host.resolve_ollama_host",
        wraps=resolve_ollama_host,
    ) as resolve_mock:
        with patch(
            "dockai.llm.resolve_host._default_probe",
            return_value=True,
        ):
            with patch(
                "dockai.llm.resolve_host._model_available",
                return_value=True,
            ):
                _prepare_ollama_settings(settings)
                _prepare_ollama_settings(settings)
    assert resolve_mock.call_count == 2


def test_docker_only_skips_resolution():
    """containers subcommand does not import prepare path — smoke via no call."""
    from typer.testing import CliRunner

    from dockai.cli import app

    runner = CliRunner()
    with patch("dockai.cli._prepare_ollama_settings") as prepare:
        with patch("dockai.cli.get_client") as get_client:
            get_client.return_value = MagicMock()
            with patch("dockai.cli.list_containers", return_value=[]):
                with patch("dockai.cli._ctx_settings") as ctx_settings:
                    ctx_settings.return_value = _settings("http://127.0.0.1:11434")
                    result = runner.invoke(app, ["containers"])
    assert result.exit_code == 0
    prepare.assert_not_called()
