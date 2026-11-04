"""Compose start prompt (A / B / N)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dockai.cli import _offer_compose_start
from dockai.compose_context import ComposeProjectStatus, ComposeServiceStatus


def _status() -> ComposeProjectStatus:
    return ComposeProjectStatus(
        compose_file=Path("/tmp/compose.yaml"),
        project_name="demo",
        services=(
            ComposeServiceStatus(name="web", state="running"),
            ComposeServiceStatus(name="db", state="stopped", container_name="demo-db-1"),
        ),
    )


def test_offer_compose_start_all():
    with (
        patch("dockai.cli.typer.prompt", return_value="A"),
        patch("dockai.cli.compose_up") as up,
        patch("dockai.cli.busy_status"),
    ):
        _offer_compose_start(_status(), Path("/tmp/compose.yaml"))
    up.assert_called_once_with(Path("/tmp/compose.yaml"), services=["db"])


def test_offer_compose_start_noop():
    with patch("dockai.cli.typer.prompt", return_value="N"):
        _offer_compose_start(_status(), Path("/tmp/compose.yaml"))


def test_offer_compose_start_choose_one():
    with (
        patch("dockai.cli.typer.prompt", side_effect=["B", 1]),
        patch("dockai.cli.compose_up") as up,
        patch("dockai.cli.busy_status"),
    ):
        _offer_compose_start(_status(), Path("/tmp/compose.yaml"))
    up.assert_called_once_with(Path("/tmp/compose.yaml"), services=["db"])
