"""Shared pytest fixtures with mocked Docker containers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def make_container(
    *,
    cid: str = "a" * 64,
    name: str = "api-server",
    status: str = "running",
    image_tags: list[str] | None = None,
    started_at: str = "2026-10-11T04:00:00Z",
    finished_at: str = "0001-01-01T00:00:00Z",
    restart_count: int = 0,
    restarting: bool = False,
    exit_code: int = 0,
    oom_killed: bool = False,
    error: str = "",
    logs: bytes = b"line1\nline2\n",
) -> MagicMock:
    container = MagicMock()
    container.id = cid
    container.name = name
    container.status = status
    container.image = SimpleNamespace(tags=image_tags or ["nginx:latest"], short_id="sha256:abc")
    container.attrs = {
        "Names": [f"/{name}"],
        "Config": {"Image": "nginx:latest"},
        "State": {
            "Status": status,
            "StartedAt": started_at,
            "FinishedAt": finished_at,
            "RestartCount": restart_count,
            "Restarting": restarting,
            "ExitCode": exit_code,
            "OOMKilled": oom_killed,
            "Error": error,
            "Pid": 1234 if status == "running" else 0,
            "Health": {"Status": "healthy"},
        },
    }
    container.logs.return_value = logs
    container.reload.return_value = None
    return container


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()
