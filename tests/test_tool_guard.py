"""Issue 8: agent must not answer Docker facts from chat memory alone."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from dockai.agent.loop import _NUDGE_DOCKER, _should_nudge_missing_docker_call, run_agent
from dockai.agent.session import ChatSession
from dockai.agent.shortcuts import needs_docker_tool
from dockai.llm.base import ChatMessage, ToolCall
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_needs_docker_tool_covers_logs_inspect_uptime_lifecycle():
    assert needs_docker_tool("can we dig into the logs for api-server")
    assert needs_docker_tool("inspect the api-server container")
    assert needs_docker_tool("show uptime for my api-server container")
    assert needs_docker_tool("could you restart the api-server container")
    assert not needs_docker_tool("why might a container keep restarting?")


def test_should_nudge_when_logs_intent_and_no_tool_this_turn():
    assert _should_nudge_missing_docker_call(
        "show logs for api-server",
        focus_container=None,
        collected=[],
        answer="Here are the last lines from memory.",
    )


def test_should_not_nudge_when_tool_ran_this_turn():
    assert not _should_nudge_missing_docker_call(
        "show logs for api-server",
        focus_container=None,
        collected=[{"tool": "get_container_logs", "result": {"ok": True}}],
        answer="Done.",
    )


def test_should_nudge_stale_not_found_claim_without_tools():
    """Text-only 'not found' must retry even if intent heuristics are weak."""
    assert _should_nudge_missing_docker_call(
        "tell me more",
        focus_container="api-server",
        collected=[],
        answer="That container was not found on the host.",
    )


def test_regression_scripted_llm_not_found_without_tools_after_prior_failure():
    """
    Scripted model tries to answer 'not found' without tools after a failed turn;
    nudge must force get_container_logs on the corrected name.
    """
    client = MagicMock()
    container = make_container(name="saien-backend-api", logs=b"log-line\n")
    client.containers.list.return_value = [container]
    client.containers.get.side_effect = NotFound("missing")

    history = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="inspect bad-name-xyz"),
        ChatMessage(
            role="tool",
            name="inspect_container",
            content='{"ok": false, "error": "No container matched \'bad-name-xyz\'."}',
        ),
        ChatMessage(
            role="assistant",
            content="No container matched that name.",
        ),
    ]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="That container still does not exist; I cannot show logs.",
            ),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="get_container_logs",
                        arguments={"target": "saien-backend-api", "tail": 100},
                    )
                ],
            ),
        ]
    )
    # Skip logs NL shortcut so the LLM text-only path is exercised first.
    with patch("dockai.agent.loop.match_shortcut", return_value=None):
        result = run_agent(
            "can we dig into the logs for saien backend api",
            llm=llm,
            client=client,
            history=history,
        )
    assert any(
        r["tool"] == "get_container_logs" and r["result"].get("ok")
        for r in result.tool_results
    )
    assert result.presentation is not None
    assert result.presentation["kind"] == "logs"
    assert any(
        m.role == "user" and m.content == _NUDGE_DOCKER for m in result.messages
    )


@pytest.mark.parametrize(
    ("user_text", "tool_name", "tool_args"),
    [
        (
            "could you inspect the saien-backend-api container",
            "inspect_container",
            {"target": "saien-backend-api"},
        ),
        (
            "show uptime for saien-backend-api container",
            "list_uptime",
            {},
        ),
        (
            "could you restart the saien-backend-api container",
            "restart_container",
            {"target": "saien-backend-api"},
        ),
    ],
)
def test_nudge_text_only_reply_then_calls_docker_tool(
    user_text: str, tool_name: str, tool_args: dict
):
    client = MagicMock()
    client.containers.list.return_value = [
        make_container(name="saien-backend-api", status="running"),
    ]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="I already know that container is missing.",
            ),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(id="1", name=tool_name, arguments=tool_args),
                ],
            ),
        ]
    )
    with patch("dockai.agent.loop.match_shortcut", return_value=None):
        result = run_agent(user_text, llm=llm, client=client)
    assert any(
        item["tool"] == tool_name and item["result"].get("ok")
        for item in result.tool_results
    )
    assert any(
        m.role == "user" and m.content == _NUDGE_DOCKER for m in result.messages
    )


def test_session_corrected_name_after_failed_inspect_calls_logs_tool():
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
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="get_container_logs",
                        arguments={"target": "saien-backend-api", "tail": 50},
                    )
                ],
            ),
        ]
    )
    session = ChatSession(llm=llm, client=client)
    failed = session.ask("inspect totally-missing-name-000")
    assert failed.tool_results[0]["result"]["ok"] is False

    with patch("dockai.agent.loop.match_shortcut", return_value=None):
        recovered = session.ask("saien backend api logs for last 50 lines")
    assert any(
        t["tool"] == "get_container_logs" and t["result"].get("ok")
        for t in recovered.tool_results
    )
    assert recovered.presentation is not None
    assert recovered.presentation["kind"] == "logs"
