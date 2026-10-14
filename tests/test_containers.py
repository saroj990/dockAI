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
from dockai.tools.containers import _primary_name
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


def test_resolve_ignores_spaces_and_hyphens(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="saien-backend-api"),
        make_container(cid="c" * 64, name="nginx"),
    ]
    container = resolve_container(mock_client, "saien backend api")
    assert _primary_name(container) == "saien-backend-api"


def test_resolve_normalized_underscores(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="f" * 64, name="my_app_server"),
    ]
    container = resolve_container(mock_client, "my-app server")
    assert _primary_name(container) == "my_app_server"


def test_resolve_not_found(mock_client):
    mock_client.containers.list.return_value = []
    mock_client.containers.get.side_effect = NotFound("missing")
    with pytest.raises(ContainerNotFoundError):
        resolve_container(mock_client, "nope")


def test_resolve_typo_single_close_match(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="saien-backend-api"),
        make_container(cid="c" * 64, name="nginx"),
    ]
    container = resolve_container(mock_client, "saen-backend-api")
    assert _primary_name(container) == "saien-backend-api"


def test_resolve_typo_alternate_spellings(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="saien-backend-api"),
    ]
    for target in ("saie-backend-api", "saienn-backend-api", "saen backend api"):
        container = resolve_container(mock_client, target)
        assert _primary_name(container) == "saien-backend-api"


def test_resolve_typo_unrelated_still_not_found(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="saien-backend-api"),
    ]
    mock_client.containers.get.side_effect = NotFound("missing")
    with pytest.raises(ContainerNotFoundError):
        resolve_container(mock_client, "redis-cache")


def test_resolve_typo_short_target_not_fuzzy(mock_client):
    """Short targets must not fuzzy-match (safety)."""
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="api-server"),
        make_container(cid="c" * 64, name="app-server"),
    ]
    mock_client.containers.get.side_effect = NotFound("missing")
    # "apo" is short + not a substring of either after normalization path fails
    with pytest.raises(ContainerNotFoundError):
        resolve_container(mock_client, "apo")


def test_resolve_typo_hex_id_not_fuzzy(mock_client):
    """Hex-like targets are treated as IDs — never fuzzy to a name."""
    real_id = "abcdef0123456789" + "0" * 48
    mock_client.containers.list.return_value = [
        make_container(cid=real_id, name="saien-backend-api"),
    ]
    mock_client.containers.get.side_effect = NotFound("missing")
    # Near-miss hex that is not a prefix of real_id
    with pytest.raises(ContainerNotFoundError):
        resolve_container(mock_client, "abcdef0123456788" + "0" * 48)


def test_resolve_typo_multiple_close_is_ambiguous(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="worker-service-a"),
        make_container(cid="c" * 64, name="worker-service-b"),
    ]
    with pytest.raises(AmbiguousContainerError) as exc:
        resolve_container(mock_client, "worker-service-x")
    assert len(exc.value.matches) >= 2


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
