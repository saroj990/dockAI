from unittest.mock import MagicMock

from docker.errors import NotFound

from dockai.agent.loop import _next_focus, run_agent
from dockai.agent.session import ChatSession
from dockai.llm.base import ChatMessage, ToolCall
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_focus_set_from_single_inspect():
    collected = [
        {
            "tool": "inspect_container",
            "arguments": {"target": "api"},
            "result": {
                "ok": True,
                "data": {"name": "saien-backend-api", "status": "running"},
            },
        }
    ]
    assert _next_focus(collected, None) == "saien-backend-api"


def test_focus_cleared_when_multiple_containers():
    collected = [
        {
            "tool": "list_containers",
            "arguments": {},
            "result": {
                "ok": True,
                "data": [
                    {"name": "a"},
                    {"name": "b"},
                ],
            },
        }
    ]
    assert _next_focus(collected, "a") is None


def test_focus_kept_when_no_new_names():
    collected = [
        {
            "tool": "nope",
            "arguments": {},
            "result": {"ok": False, "error": "Unknown tool"},
        }
    ]
    assert _next_focus(collected, "kept") == "kept"


def test_session_follow_up_uses_history_and_focus():
    client = MagicMock()
    client.containers.list.return_value = [
        make_container(name="saien-backend-api", logs=b"line\n")
    ]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="inspect_container",
                        arguments={"target": "saien-backend-api"},
                    )
                ],
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
        ]
    )
    session = ChatSession(llm=llm, client=client)
    first = session.ask("inspect saien-backend-api")
    assert session.focus_container == "saien-backend-api"
    assert first.presentation is not None
    assert first.presentation["kind"] == "inspect"

    second = session.ask("show its last 25 log lines")
    assert second.presentation is not None
    assert second.presentation["kind"] == "logs"
    # follow-up user message should include focus context
    user_msgs = [m.content for m in session.messages if m.role == "user"]
    assert any("focused container is 'saien-backend-api'" in (c or "") for c in user_msgs)


def test_session_retries_docker_after_prior_failure_without_tool_hallucination():
    """After a failed lookup, a corrected ask must not answer from memory alone."""
    client = MagicMock()
    container = make_container(name="saien-backend-api", logs=b"line\n")
    client.containers.list.return_value = [container]
    client.containers.get.side_effect = NotFound("missing")
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="No container matched that name.",
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "That container still does not exist; I cannot show logs."
                ),
            ),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="get_container_logs",
                        arguments={
                            "target": "saien-backend-api",
                            "tail": 150,
                        },
                    )
                ],
            ),
        ]
    )
    session = ChatSession(llm=llm, client=client)
    first = session.ask("inspect totally-missing-name-000")
    assert first.tool_results[0]["result"]["ok"] is False

    second = session.ask("saien backend api logs for last 150 lines")
    assert second.presentation is not None
    assert second.presentation["kind"] == "logs"
    assert any(
        item["tool"] == "get_container_logs" for item in second.tool_results
    )
    assert "saien-backend-api" in second.answer


def test_run_agent_history_does_not_reset_system():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="api-server")]
    history = [ChatMessage(role="system", content="sys")]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="1", name="list_containers", arguments={})],
            ),
            ChatMessage(role="assistant", content="one"),
        ]
    )
    result = run_agent("list", llm=llm, client=client, history=history)
    assert result.messages[0].content == "sys"
    assert result.presentation is not None
    assert "Showing" in result.answer
