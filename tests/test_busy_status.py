"""Elapsed time on CLI spinner / busy_status."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dockai.formatting import (
    ElapsedStatusHandle,
    append_elapsed_to_status_message,
    format_elapsed,
)


def test_format_elapsed_unchanged_for_loader():
    assert format_elapsed(0.42) == "420 ms"
    assert format_elapsed(12.34) == "12.3s"


def test_append_elapsed_to_status_message():
    assert append_elapsed_to_status_message("Working on it", 0.42) == (
        "Working on it (420 ms)"
    )
    assert append_elapsed_to_status_message("Asking the model (1.0s)", 3.0) == (
        "Asking the model (3.0s)"
    )
    assert append_elapsed_to_status_message(
        "[cyan]Fetching from Docker[/cyan]", 2.5
    ) == "Fetching from Docker (2.5s)"


def test_busy_status_updates_message_with_elapsed():
    status = MagicMock()
    handle = ElapsedStatusHandle(status, start=100.0, tick_interval=10.0)
    handle.update("Working on it")
    with patch("dockai.formatting.time.perf_counter", return_value=103.2):
        handle._render()
    status.update.assert_called_with("[cyan]Working on it (3.2s)[/cyan]")


def test_progress_callback_includes_elapsed():
    status = MagicMock()
    handle = ElapsedStatusHandle(status, start=50.0, tick_interval=10.0)
    with patch("dockai.formatting.time.perf_counter", return_value=53.0):
        handle.update("Asking the model — please wait…")
    call = status.update.call_args[0][0]
    assert "Asking the model" in call
    assert "3.0s" in call


def test_cli_ask_still_prints_completed_footer():
    from dockai.agent.loop import AgentResult
    from dockai.cli import _run_ask
    from dockai.config import Settings

    cfg = Settings(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="test",
        ollama_timeout=30.0,
        docker_timeout=60.0,
        verbose=False,
        config_path=None,
    )
    result = AgentResult(answer="ok", timings=[("shortcut:list", 0.01)])

    with (
        patch("dockai.cli.OllamaProvider") as provider_cls,
        patch("dockai.cli.get_client", return_value=MagicMock()),
        patch("dockai.cli.run_agent", return_value=result),
        patch("dockai.cli.print_elapsed") as print_elapsed,
        patch("dockai.cli.busy_status") as busy_status,
    ):
        busy_status.return_value.__enter__ = MagicMock(
            return_value=MagicMock(update=MagicMock())
        )
        busy_status.return_value.__exit__ = MagicMock(return_value=False)
        provider_cls.return_value.close = MagicMock()
        _run_ask("list containers", settings=cfg)

    print_elapsed.assert_called_once()
    assert print_elapsed.call_args[0][1] == [("shortcut:list", 0.01)]
