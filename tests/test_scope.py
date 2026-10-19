from unittest.mock import MagicMock

from dockai.agent.loop import run_agent
from dockai.agent.scope import (
    apply_list_scope,
    detect_status_filter,
    wants_all_containers,
    wants_running_only,
)
from dockai.agent.shortcuts import match_shortcut
from dockai.llm.base import ChatMessage, ToolCall
from dockai.tools.containers import list_containers
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_wants_running_only_phrases():
    assert wants_running_only("show me only running containers")
    assert wants_running_only("can you pull only name and uptime of running containers")
    assert wants_running_only("list containers that are running")
    assert wants_running_only("show all running containers")
    assert not wants_running_only("list all containers")
    assert not wants_running_only("show stopped containers")
    assert not wants_running_only("containers including exited")


def test_wants_all_containers_phrases():
    assert wants_all_containers("list all containers")
    assert wants_all_containers("show stopped containers")
    assert wants_all_containers("show me exited containers")
    assert not wants_all_containers("show all running containers")
    assert not wants_all_containers("show me only running containers")


def test_detect_status_filter():
    assert detect_status_filter("show me exited containers") == "exited"
    assert detect_status_filter("show stopped containers") == "stopped"
    assert detect_status_filter("list dead containers") == "dead"
    assert detect_status_filter("show running containers") == "running"
    assert detect_status_filter("list all containers") is None
    assert detect_status_filter("containers including exited") is None
    assert detect_status_filter("show me inactive containers") == "not_running"
    assert (
        detect_status_filter("show me containers which not running right now")
        == "not_running"
    )
    assert detect_status_filter("not running") == "not_running"
    assert (
        detect_status_filter("list all containers except running ones")
        == "not_running"
    )


def test_apply_list_scope_forces_running():
    forced = apply_list_scope(
        "only name and uptime of running containers",
        "list_containers",
        {"all_containers": True, "columns": ["name", "uptime"]},
    )
    assert forced["all_containers"] is False
    assert forced["columns"] == ["name", "uptime"]
    assert "status" not in forced

    search = apply_list_scope(
        "find running containers named api",
        "search_containers",
        {"keyword": "api", "running_only": False},
    )
    assert search["running_only"] is True


def test_apply_list_scope_exited():
    forced = apply_list_scope(
        "show me exited containers",
        "list_containers",
        {"all_containers": True},
    )
    assert forced["all_containers"] is True
    assert forced["status"] == "exited"

    # Model forgot status — still enforced
    forced2 = apply_list_scope(
        "show me exited containers",
        "list_containers",
        {"all_containers": True},
    )
    assert forced2["status"] == "exited"


def test_apply_list_scope_leaves_all_asks():
    kept = apply_list_scope(
        "list all containers",
        "list_containers",
        {"all_containers": True},
    )
    assert kept["all_containers"] is True
    assert "status" not in kept


def test_shortcut_only_running_containers():
    s = match_shortcut("show me only running containers")
    assert s is not None
    assert s.tool == "list_containers"
    assert s.arguments["all_containers"] is False


def test_shortcut_exited_containers():
    s = match_shortcut("show me exited containers")
    assert s is not None
    assert s.tool == "list_containers"
    assert s.arguments["all_containers"] is True
    assert s.arguments["status"] == "exited"


def test_shortcut_stopped_containers():
    s = match_shortcut("show stopped containers")
    assert s is not None
    assert s.arguments["status"] == "stopped"
    assert s.arguments["all_containers"] is True


def test_list_containers_status_filter(mock_client):
    running = make_container(name="api", status="running")
    exited = make_container(name="old", status="exited", cid="b" * 64)
    mock_client.containers.list.return_value = [running, exited]
    rows = list_containers(mock_client, all_containers=True, status="exited")
    assert len(rows) == 1
    assert rows[0]["name"] == "old"
    assert rows[0]["status"] == "exited"


def test_run_agent_overrides_model_all_containers():
    """Even if the model passes all_containers=true, running intent wins."""
    running = make_container(name="api-server", status="running")
    exited = make_container(name="old-job", status="exited")
    client = MagicMock()
    client.containers.list.side_effect = lambda all=False, **_: (
        [running, exited] if all else [running]
    )

    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="list_containers",
                        arguments={"all_containers": True, "columns": ["name", "uptime"]},
                    )
                ],
            ),
        ]
    )
    result = run_agent(
        "please display name and uptime for containers that are running thanks",
        llm=llm,
        client=client,
    )
    assert result.tool_results
    args = result.tool_results[0]["arguments"]
    assert args["all_containers"] is False
    client.containers.list.assert_called_with(all=False)


def test_run_agent_exited_shortcut_filters():
    running = make_container(name="api-server", status="running")
    exited = make_container(name="old-job", status="exited", cid="b" * 64)
    client = MagicMock()
    client.containers.list.return_value = [running, exited]
    llm = ScriptedLLM(
        [ChatMessage(role="assistant", content="should-not-be-called")]
    )
    result = run_agent(
        "show me exited containers",
        llm=llm,
        client=client,
    )
    assert result.presentation is not None
    rows = result.presentation["rows"]
    assert len(rows) == 1
    assert rows[0]["name"] == "old-job"
    assert not any(label.startswith("ollama") for label, _ in result.timings)
