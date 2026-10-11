"""Acceptance scenarios AT-01..AT-15 (mocked Docker / controlled agent)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from docker.errors import NotFound

from dockai.agent.loop import run_agent
from dockai.agent.registry import build_registry, execute_tool
from dockai.errors import AmbiguousContainerError, ContainerNotFoundError, DockerUnavailableError
from dockai.llm.base import ChatMessage, ToolCall
from dockai.tools.containers import (
    DEFAULT_LOG_TAIL,
    MAX_FULL_LOG_CHARS,
    get_container_logs,
    list_containers,
    resolve_container,
    search_containers,
)
from dockai.tools.lifecycle import apply_action, propose_action
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_at01_list_running_only(mock_client):
    mock_client.containers.list.return_value = [
        make_container(name="api-server", status="running"),
    ]
    rows = list_containers(mock_client, all_containers=False)
    mock_client.containers.list.assert_called_with(all=False)
    assert [r["name"] for r in rows] == ["api-server"]


def test_at02_logs_default_100(mock_client):
    c = make_container(name="api-server", logs=b"x\n")
    mock_client.containers.list.return_value = [c]
    result = get_container_logs(mock_client, "api-server")
    assert result["tail"] == DEFAULT_LOG_TAIL == 100
    c.logs.assert_called_with(stdout=True, stderr=True, timestamps=False, tail=100)


def test_at03_logs_tail_25(mock_client):
    c = make_container(name="api-server", logs=b"x\n")
    mock_client.containers.list.return_value = [c]
    result = get_container_logs(mock_client, "api-server", tail=25)
    assert result["tail"] == 25


def test_at04_full_logs_mode(mock_client):
    c = make_container(name="api-server", logs=b"full\n")
    mock_client.containers.list.return_value = [c]
    result = get_container_logs(mock_client, "api-server", full=True)
    assert result["mode"] == "full"
    assert "available from Docker" in result["note"]


def test_at05_restart_troubleshooting_evidence(mock_client):
    c = make_container(
        name="flaky",
        status="restarting",
        restart_count=4,
        restarting=True,
        logs=b"panic: oom\n",
    )
    mock_client.containers.list.return_value = [c]
    listed = execute_tool(
        build_registry(), mock_client, "list_restarting_containers", {}
    )
    assert listed["ok"] is True
    assert listed["data"]["containers"][0]["restarts"] == 4
    inspected = execute_tool(
        build_registry(), mock_client, "inspect_container", {"target": "flaky"}
    )
    logs = execute_tool(
        build_registry(),
        mock_client,
        "get_container_logs",
        {"target": "flaky", "tail": 100},
    )
    assert inspected["data"]["restarting"] is True
    assert "oom" in logs["data"]["logs"]


def test_at06_uptime_running_and_stopped(mock_client):
    running = make_container(name="up", status="running")
    stopped = make_container(
        cid="b" * 64,
        name="down",
        status="exited",
        finished_at="2026-10-11T05:00:00Z",
    )
    mock_client.containers.list.return_value = [running, stopped]
    rows = list_containers(mock_client, all_containers=True)
    by_name = {r["name"]: r for r in rows}
    assert by_name["up"]["uptime"]["kind"] == "uptime"
    assert by_name["down"]["uptime"]["kind"] == "stopped"


def test_at07_table_fields_present(mock_client):
    mock_client.containers.list.return_value = [make_container(name="api-server")]
    row = list_containers(mock_client)[0]
    assert {"id", "name", "status"}.issubset(row)


def test_at08_search_case_insensitive_scope(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="b" * 64, name="Flink-Job"),
        make_container(cid="c" * 64, name="nginx"),
    ]
    result = search_containers(mock_client, "flink")
    assert result["scope"] == "all"
    assert result["count"] == 1


def test_at09_stop_proposes_confirmation(mock_client):
    mock_client.containers.list.return_value = [make_container(name="api-server")]
    proposal = propose_action(mock_client, "stop", "api-server")
    assert proposal["needs_confirmation"] is True
    assert "Stop" in proposal["impact"] or "stop" in proposal["impact"].lower()


def test_at10_deny_means_no_execute(mock_client):
    c = make_container(name="api-server")
    mock_client.containers.list.return_value = [c]
    propose_action(mock_client, "stop", "api-server")
    # User said no — apply is never called
    c.stop.assert_not_called()


def test_at11_ambiguous_target(mock_client):
    mock_client.containers.list.return_value = [
        make_container(cid="d" * 64, name="api-server"),
        make_container(cid="e" * 64, name="api-server-worker"),
    ]
    with pytest.raises(AmbiguousContainerError):
        resolve_container(mock_client, "api")


def test_at12_missing_and_docker_errors(mock_client):
    mock_client.containers.list.return_value = []
    mock_client.containers.get.side_effect = NotFound("missing")
    with pytest.raises(ContainerNotFoundError):
        resolve_container(mock_client, "nope")

    from dockai.docker_client import get_client
    from docker.errors import DockerException
    from unittest.mock import patch

    with patch("dockai.docker_client.docker.from_env", side_effect=DockerException("down")):
        with pytest.raises(DockerUnavailableError):
            get_client()


def test_at13_invalid_tool_args():
    result = execute_tool(
        build_registry(),
        MagicMock(),
        "get_container_logs",
        {"__invalid__": "{"},
    )
    assert result["ok"] is False


def test_at14_stop_verifies_outcome(mock_client):
    c = make_container(name="api-server", status="running")

    def _stop():
        c.attrs["State"]["Status"] = "exited"
        c.status = "exited"

    c.stop.side_effect = _stop
    mock_client.containers.list.return_value = [c]
    outcome = apply_action(mock_client, "stop", "api-server")
    assert outcome["after"]["status"] == "exited"
    assert "finished" in outcome["message"].lower() or "Status" in outcome["message"]


def test_at15_empty_and_truncated_logs(mock_client):
    empty = make_container(name="api-server", logs=b"")
    mock_client.containers.list.return_value = [empty]
    empty_result = get_container_logs(mock_client, "api-server", full=True)
    assert empty_result["empty"] is True

    huge = make_container(name="api-server", logs=("Z" * (MAX_FULL_LOG_CHARS + 50)).encode())
    mock_client.containers.list.return_value = [huge]
    huge_result = get_container_logs(mock_client, "api-server", full=True)
    assert huge_result["truncated"] is True
    assert len(huge_result["logs"]) == MAX_FULL_LOG_CHARS


def test_at09_agent_pending_stop():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="api-server")]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="stop_container",
                        arguments={"target": "api-server"},
                    )
                ],
            )
        ]
    )
    result = run_agent("Stop api-server.", llm=llm, client=client)
    assert result.pending_action is not None
    assert result.pending_action["needs_confirmation"] is True
