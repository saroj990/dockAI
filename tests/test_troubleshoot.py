"""troubleshoot_container_logs and analyze_log_text."""

from __future__ import annotations

from unittest.mock import MagicMock

from dockai.agent.registry import build_registry, execute_tool
from dockai.tools.troubleshoot import (
    DEFAULT_TROUBLESHOOT_TAIL,
    analyze_log_text,
    troubleshoot_container_logs,
)
from tests.conftest import make_container


def test_analyze_log_text_detects_oom_and_panic():
    text = "INFO starting\npanic: oom\nError: process killed\n"
    result = analyze_log_text(text)
    assert result["signal_line_count"] >= 2
    assert "oom" in result["categories"] or "panic" in result["categories"]
    assert result["highlight_lines"][0]["line"] == 2


def test_analyze_log_text_clean_logs():
    result = analyze_log_text("hello\nworld\n")
    assert result["signal_line_count"] == 0
    assert result["highlight_lines"] == []


def test_analyze_log_text_traceback():
    text = "Traceback (most recent call last):\n  File x.py\nValueError: bad\n"
    result = analyze_log_text(text)
    assert result["has_traceback"] is True
    assert "traceback" in result["categories"]


def test_troubleshoot_container_logs_integration(mock_client):
    container = make_container(
        name="flaky",
        status="restarting",
        restart_count=3,
        restarting=True,
        logs=b"panic: oom\nError: exit\n",
    )
    mock_client.containers.list.return_value = [container]
    data = troubleshoot_container_logs(mock_client, "flaky", tail=50)
    assert data["container"] == "flaky"
    assert data["inspect"]["restarts"] == 3
    assert data["analysis"]["signal_line_count"] >= 1
    assert "oom" in data["logs"]["logs"]


def test_troubleshoot_tool_via_registry(mock_client):
    container = make_container(
        name="api-server",
        logs=b"FATAL: connection refused\n",
    )
    mock_client.containers.list.return_value = [container]
    result = execute_tool(
        build_registry(),
        mock_client,
        "troubleshoot_container_logs",
        {"target": "api-server"},
    )
    assert result["ok"] is True
    assert result["data"]["analysis"]["signal_line_count"] >= 1
    container.logs.assert_called_with(
        stdout=True,
        stderr=True,
        timestamps=False,
        tail=DEFAULT_TROUBLESHOOT_TAIL,
    )


def test_troubleshoot_custom_tail(mock_client):
    container = make_container(name="api-server", logs=b"x\n")
    mock_client.containers.list.return_value = [container]
    execute_tool(
        build_registry(),
        mock_client,
        "troubleshoot_container_logs",
        {"target": "api-server", "tail": 25},
    )
    container.logs.assert_called_with(
        stdout=True,
        stderr=True,
        timestamps=False,
        tail=25,
    )
