"""Phase 2: registry validation and tool-calling loop (mocked LLM/Docker)."""

from __future__ import annotations

from unittest.mock import MagicMock

from dockai.agent.loop import run_agent
from dockai.agent.registry import build_registry, execute_tool
from dockai.llm.base import ChatMessage, ToolCall
from tests.conftest import make_container


class ScriptedLLM:
    def __init__(self, responses: list[ChatMessage]) -> None:
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages, tools):
        self.calls.append(list(messages))
        if not self.responses:
            return ChatMessage(role="assistant", content="fallback")
        return self.responses.pop(0)


def test_unknown_tool_does_not_fabricate():
    client = MagicMock()
    result = execute_tool(build_registry(), client, "rm_all", {})
    assert result["ok"] is False
    assert "Unknown tool" in result["error"]
    client.containers.list.assert_not_called()


def test_invalid_args_rejected():
    client = MagicMock()
    result = execute_tool(
        build_registry(),
        client,
        "inspect_container",
        {"target": "api", "extra": 1},
    )
    assert result["ok"] is False
    assert "Unexpected" in result["error"]


def test_missing_required_arg():
    result = execute_tool(build_registry(), MagicMock(), "get_container_logs", {})
    assert result["ok"] is False
    assert "Missing" in result["error"]


def test_bad_json_arguments_flag():
    result = execute_tool(
        build_registry(),
        MagicMock(),
        "list_containers",
        {"__invalid__": "{bad"},
    )
    assert result["ok"] is False


def test_tool_error_surfaced_not_invented():
    client = MagicMock()
    client.containers.list.return_value = []
    client.containers.get.side_effect = Exception("boom")
    # resolve will NotFound path - use empty list + NotFound
    from docker.errors import NotFound

    client.containers.get.side_effect = NotFound("missing")
    result = execute_tool(
        build_registry(),
        client,
        "inspect_container",
        {"target": "missing"},
    )
    assert result["ok"] is False
    assert "No container matched" in result["error"]


def test_agent_loop_calls_tool_then_answers():
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
            ChatMessage(
                role="assistant",
                content="Running: api-server",
            ),
        ]
    )
    progress: list[str] = []
    result = run_agent(
        "show running containers",
        llm=llm,
        client=client,
        on_progress=progress.append,
    )
    assert result.presentation is not None
    assert "Showing 1 container" in result.answer
    assert result.tool_results[0]["result"]["ok"] is True
    assert result.tool_results[0]["result"]["data"][0]["name"] == "api-server"
    # NL shortcut skips Ollama (turns=0); otherwise one tool round (turns=1).
    assert result.turns in {0, 1}
    assert llm.responses  # model unused when shortcut/table-first applies
    assert any(
        "shortcut" in label or label.startswith("ollama") or "Docker" in label
        for label, _ in result.timings
    ) or any("shortcut" in m.lower() or "model" in m.lower() for m in progress)


def test_agent_reports_failed_tool_without_fake_success():
    client = MagicMock()
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="1", name="nope", arguments={})],
            ),
            ChatMessage(
                role="assistant",
                content="Tool failed: unknown tool 'nope'.",
            ),
        ]
    )
    result = run_agent("do something", llm=llm, client=client)
    assert result.tool_results[0]["result"]["ok"] is False
    assert "unknown tool" in result.answer.lower() or "failed" in result.answer.lower()


def test_coerce_string_tail_and_bool_full():
    client = MagicMock()
    container = make_container(name="saien-backend-api", logs=b"line\n")
    client.containers.list.return_value = [container]
    result = execute_tool(
        build_registry(),
        client,
        "get_container_logs",
        {"target": "saien-backend-api", "tail": "25", "full": "false"},
    )
    assert result["ok"] is True
    container.logs.assert_called_once_with(
        stdout=True,
        stderr=True,
        timestamps=False,
        tail=25,
    )


def test_agent_rejects_tool_json_dump_and_recovers():
    client = MagicMock()
    container = make_container(name="saien-backend-api", logs=b"ok\n")
    client.containers.list.return_value = [container]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content=(
                    'Let me try again.\n'
                    '{"name": "get_container_logs", '
                    '"parameters": {"tail": 25, "target": "saien-backend-api"}}'
                ),
            ),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="get_container_logs",
                        arguments={"target": "saien-backend-api", "tail": 25},
                    )
                ],
            ),
            ChatMessage(role="assistant", content="Last 25 lines:\nok"),
        ]
    )
    result = run_agent("show last 25 lines", llm=llm, client=client)
    assert result.presentation is not None
    assert result.presentation["kind"] == "logs"
    assert "saien-backend-api" in result.answer
    assert any(r["result"].get("ok") for r in result.tool_results)


def test_agent_nudges_text_only_docker_answer_without_tools():
    """Model must not answer logs/inspect from chat memory in the same turn."""
    client = MagicMock()
    container = make_container(name="saien-backend-api", logs=b"ok\n")
    client.containers.list.return_value = [container]
    history = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="inspect missing"),
        ChatMessage(
            role="assistant",
            content="The container was not found.",
        ),
    ]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="That container still does not exist.",
            ),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="get_container_logs",
                        arguments={"target": "saien-backend-api", "tail": 50},
                    )
                ],
            ),
        ]
    )
    result = run_agent(
        "can we dig into the logs for saien backend api",
        llm=llm,
        client=client,
        history=history,
    )
    assert result.presentation is not None
    assert result.presentation["kind"] == "logs"
    assert any(
        r["tool"] == "get_container_logs" and r["result"].get("ok")
        for r in result.tool_results
    )


def test_agent_max_turns_uses_last_tool_error():
    client = MagicMock()
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="1", name="nope", arguments={})],
            ),
            ChatMessage(
                role="assistant",
                content='{"name": "nope", "parameters": {}}',
            ),
            ChatMessage(
                role="assistant",
                content='{"name": "nope", "parameters": {}}',
            ),
        ]
    )
    result = run_agent("x", llm=llm, client=client, max_turns=3)
    assert "could not complete" in result.answer.lower()
    assert "Unknown tool" in result.answer or "unknown tool" in result.answer.lower()
