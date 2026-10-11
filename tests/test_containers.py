from unittest.mock import MagicMock

import pytest
from docker.errors import NotFound

from dockai.errors import AmbiguousContainerError, ContainerNotFoundError
from dockai.tools.containers import (
    DEFAULT_LOG_TAIL,
    get_container_logs,
    inspect_container,
    list_containers,
    resolve_container,
    search_containers,
)
from tests.conftest import make_container


def test_list_containers_running_only(mock_client):
    running = make_container(name="api-server")
    mock_client.containers.list.return_value = [running]
    result = list_containers(mock_client, all_containers=False)
    mock_client.containers.list.assert_called_once_with(all=False)
    assert len(result) == 1
    assert result[0]["name"] == "api-server"
    assert result[0]["id"] == "a" * 12
    assert result[0]["uptime"]["kind"] == "uptime"


def test_search_case_insensitive_all_scope(mock_client):
    containers = [
        make_container(cid="b" * 64, name="Flink-JobManager"),
        make_container(cid="c" * 64, name="nginx"),
    ]
    mock_client.containers.list.return_value = containers
    result = search_containers(mock_client, "flink")
    assert result["scope"] == "all"
    assert result["count"] == 1
    assert result["matches"][0]["name"] == "Flink-JobManager"


def test_search_running_only(mock_client):
    mock_client.containers.list.return_value = [
        make_container(name="flink-task"),
    ]
    result = search_containers(mock_client, "flink", running_only=True)
    mock_client.containers.list.assert_called_with(all=False)
    assert result["scope"] == "running"


def test_resolve_ambiguous(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="d" * 64, name="api-server"),
        make_container(cid="e" * 64, name="api-server-worker"),
    ]
    with pytest.raises(AmbiguousContainerError) as exc:
        resolve_container(mock_client, "api")
    assert len(exc.value.matches) == 2


def test_resolve_not_found(mock_client):
    mock_client.containers.list.return_value = []
    mock_client.containers.get.side_effect = NotFound("missing")
    with pytest.raises(ContainerNotFoundError):
        resolve_container(mock_client, "nope")


def test_inspect_container(mock_client):
    container = make_container(restart_count=3, restarting=True)
    mock_client.containers.list.return_value = [container]
    summary = inspect_container(mock_client, "api-server")
    assert summary["restarts"] == 3
    assert summary["restarting"] is True
    assert summary["health"] == "healthy"


def test_logs_default_tail(mock_client):
    container = make_container(logs=b"a\nb\nc\n")
    mock_client.containers.list.return_value = [container]
    result = get_container_logs(mock_client, "api-server")
    container.logs.assert_called_once_with(
        stdout=True,
        stderr=True,
        timestamps=False,
        tail=DEFAULT_LOG_TAIL,
    )
    assert result["mode"] == "tail"
    assert result["tail"] == DEFAULT_LOG_TAIL
    assert result["empty"] is False


def test_logs_custom_tail(mock_client):
    container = make_container(logs=b"x\n")
    mock_client.containers.list.return_value = [container]
    result = get_container_logs(mock_client, "api-server", tail=25)
    container.logs.assert_called_once_with(
        stdout=True,
        stderr=True,
        timestamps=False,
        tail=25,
    )
    assert result["tail"] == 25


def test_logs_full_and_empty(mock_client):
    container = make_container(logs=b"")
    mock_client.containers.list.return_value = [container]
    result = get_container_logs(mock_client, "api-server", full=True)
    assert result["mode"] == "full"
    assert result["empty"] is True


def test_logs_rejects_full_with_custom_tail(mock_client):
    mock_client.containers.list.return_value = [make_container()]
    with pytest.raises(ValueError):
        get_container_logs(mock_client, "api-server", tail=25, full=True)
