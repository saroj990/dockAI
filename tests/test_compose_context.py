"""Compose file discovery, parsing, and Docker status mapping."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dockai.compose_context import (
    ComposeContextError,
    build_compose_project_status,
    find_compose_file,
    infer_project_name,
    parse_compose_service_names,
)
from tests.conftest import make_container

FIXTURE = Path(__file__).parent / "fixtures" / "compose" / "web-db.compose.yaml"


def test_find_compose_file_success(tmp_path: Path):
    (tmp_path / "compose.yaml").write_text("services:\n  web:\n    image: x\n")
    assert find_compose_file(tmp_path) == tmp_path / "compose.yaml"


def test_find_compose_file_missing(tmp_path: Path):
    assert find_compose_file(tmp_path) is None


def test_parse_compose_service_names():
    content = FIXTURE.read_text(encoding="utf-8")
    assert parse_compose_service_names(content) == ["web", "db"]
    assert infer_project_name(FIXTURE, content) == "demo-stack"


def test_build_compose_project_status_success():
    content = FIXTURE.read_text(encoding="utf-8")
    client = MagicMock()
    client.containers.list.return_value = [
        make_container(
            name="demo-stack-web-1",
            status="running",
            cid="a" * 64,
        ),
        make_container(
            name="demo-stack-db-1",
            status="exited",
            cid="b" * 64,
        ),
    ]
    for container, service in zip(
        client.containers.list.return_value,
        ("web", "db"),
        strict=True,
    ):
        container.attrs["Config"]["Labels"] = {
            "com.docker.compose.project": "demo-stack",
            "com.docker.compose.service": service,
        }

    status = build_compose_project_status(client, FIXTURE)
    assert status.project_name == "demo-stack"
    assert status.running_count == 1
    assert status.total_count == 2
    assert status.services[0].state == "running"
    assert status.services[1].state == "stopped"


def test_build_compose_project_status_no_services(tmp_path: Path):
    bad = tmp_path / "compose.yaml"
    bad.write_text("version: '3'\n", encoding="utf-8")
    client = MagicMock()
    client.containers.list.return_value = []
    with pytest.raises(ComposeContextError, match="No services"):
        build_compose_project_status(client, bad)
