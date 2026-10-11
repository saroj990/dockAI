from unittest.mock import MagicMock

from dockai.agent.loop import run_agent
from dockai.llm.base import ChatMessage, ToolCall
from dockai.present import try_table_first
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_try_table_first_list_containers():
    batch = [
        {
            "tool": "list_containers",
            "arguments": {},
            "result": {
                "ok": True,
                "data": [{"id": "abc", "name": "api", "status": "running"}],
            },
        }
    ]
    pres = try_table_first(batch)
    assert pres is not None
    assert pres["kind"] == "containers"
    assert len(pres["rows"]) == 1


def test_try_table_first_skips_multi_tool_batch():
    batch = [
        {
            "tool": "list_containers",
            "arguments": {},
            "result": {"ok": True, "data": []},
        },
        {
            "tool": "get_container_logs",
            "arguments": {"target": "api"},
            "result": {"ok": True, "data": {"container": "api", "logs": ""}},
        },
    ]
    assert try_table_first(batch) is None


def test_try_table_first_skips_restarting_list():
    batch = [
        {
            "tool": "list_restarting_containers",
            "arguments": {},
            "result": {"ok": True, "data": {"containers": []}},
        }
    ]
    assert try_table_first(batch) is None


def test_agent_skips_second_ollama_for_list():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="api-server")]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(id="1", name="list_containers", arguments={}),
                ],
            ),
            ChatMessage(role="assistant", content="should-not-run"),
        ]
    )
    result = run_agent("show running containers", llm=llm, client=client)
    assert result.presentation is not None
    assert result.presentation["kind"] == "containers"
    assert result.answer.startswith("Showing")
    assert llm.responses  # second model reply unused
    ollama_stages = [label for label, _ in result.timings if label.startswith("ollama")]
    assert len(ollama_stages) == 1
