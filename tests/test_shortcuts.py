from unittest.mock import MagicMock

from dockai.agent.loop import run_agent
from dockai.agent.shortcuts import match_shortcut
from dockai.llm.base import ChatMessage
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_shortcut_list_running():
    s = match_shortcut("show running containers")
    assert s is not None
    assert s.tool == "list_containers"
    assert s.arguments["all_containers"] is False


def test_shortcut_name_and_uptime():
    s = match_shortcut("can you pull only name and uptime of running containers")
    assert s is not None
    assert s.tool == "list_uptime"
    assert s.arguments.get("columns") == ["name", "uptime"]
    assert s.arguments.get("all_containers") is False


def test_shortcut_logs_with_tail():
    s = match_shortcut("show last 25 lines of api-server logs")
    assert s is not None
    assert s.tool == "get_container_logs"
    assert s.arguments["target"] == "api-server"
    assert s.arguments["tail"] == 25


def test_shortcut_search():
    s = match_shortcut("find containers named flink")
    assert s is not None
    assert s.tool == "search_containers"
    assert s.arguments["keyword"] == "flink"


def test_shortcut_stop():
    s = match_shortcut("stop api-server")
    assert s is not None
    assert s.tool == "stop_container"
    assert s.arguments["target"] == "api-server"


def test_shortcut_skips_troubleshooting():
    assert match_shortcut("why is my container restarting?") is None
    assert match_shortcut("what could be wrong with api-server?") is None


def test_shortcut_focused_logs():
    s = match_shortcut(
        "show its last 25 log lines",
        focus_container="saien-backend-api",
    )
    assert s is not None
    assert s.tool == "get_container_logs"
    assert s.arguments["target"] == "saien-backend-api"
    assert s.arguments["tail"] == 25


def test_run_agent_shortcut_skips_ollama():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="api-server")]
    llm = ScriptedLLM(
        [ChatMessage(role="assistant", content="should-not-be-called")]
    )
    result = run_agent(
        "show running containers",
        llm=llm,
        client=client,
    )
    assert result.presentation is not None
    assert llm.responses  # unused
    assert any(label.startswith("shortcut:") for label, _ in result.timings)
    assert not any(label.startswith("ollama") for label, _ in result.timings)
