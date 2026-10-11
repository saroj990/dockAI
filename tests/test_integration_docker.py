"""Optional integration tests against a disposable container (not production)."""

from __future__ import annotations

import uuid

import docker
import pytest
from docker.errors import DockerException, ImageNotFound

from dockai.tools.containers import get_container_logs, list_containers, search_containers
from dockai.tools.lifecycle import apply_action, propose_action


def _docker_or_skip():
    try:
        client = docker.from_env(timeout=10)
        client.ping()
        return client
    except DockerException as exc:
        pytest.skip(f"Docker Engine not available: {exc}")


@pytest.fixture(scope="module")
def disposable():
    """Run a short-lived alpine container named uniquely for this test module."""
    client = _docker_or_skip()
    name = f"dockai-at-{uuid.uuid4().hex[:10]}"
    try:
        client.images.get("alpine:3.20")
    except ImageNotFound:
        try:
            client.images.pull("alpine", tag="3.20")
        except DockerException as exc:
            pytest.skip(f"Cannot pull alpine:3.20: {exc}")

    container = client.containers.run(
        "alpine:3.20",
        name=name,
        command=["sleep", "120"],
        detach=True,
        remove=False,
    )
    try:
        yield client, container, name
    finally:
        try:
            container.remove(force=True)
        except DockerException:
            pass


@pytest.mark.integration
def test_integration_list_and_search(disposable):
    client, _container, name = disposable
    running = list_containers(client, all_containers=False)
    assert any(row["name"] == name for row in running)
    found = search_containers(client, "dockai-at", running_only=True)
    assert found["count"] >= 1
    assert any(m["name"] == name for m in found["matches"])


@pytest.mark.integration
def test_integration_logs(disposable):
    client, container, name = disposable
    container.exec_run(["sh", "-c", "echo dockai-hello >&2"])
    # alpine sleep may not emit; write via exec to ensure logging path works
    logs = get_container_logs(client, name, tail=50)
    assert logs["container"] == name
    assert logs["mode"] == "tail"


@pytest.mark.integration
def test_integration_stop_start_with_confirm_path(disposable):
    client, _container, name = disposable
    proposal = propose_action(client, "stop", name)
    assert proposal["needs_confirmation"] is True
    stopped = apply_action(client, "stop", name)
    assert stopped["after"]["status"] in {"exited", "created", "dead"}
    started = apply_action(client, "start", name)
    assert started["after"]["status"] == "running"
