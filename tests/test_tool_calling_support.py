"""Fail-fast when the LLM never returns tool_calls on Docker-required asks."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dockai.agent.loop import run_agent, tool_calling_unsupported_message
from dockai.errors import ToolCallingUnsupportedError
from dockai.llm.base import ChatMessage, ToolCall
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


class IdentifiedLLM(ScriptedLLM):
    """ScriptedLLM with model/host for error message tests."""

    model = "deepseek-r1:14b"
    host = "http://203.0.113.99:11434"


def test_tool_calling_unsupported_message_includes_model_and_host():
    msg = tool_calling_unsupported_message(
        model="deepseek-r1:14b",
        host="http://203.0.113.99:11434",
    )
    assert "deepseek-r1:14b" in msg
    assert "203.0.113.99:11434" in msg
    assert "tool calls" in msg.lower()
    assert "qwen2.5:3b" in msg
    assert "dockai logs" in msg


def test_fail_fast_no_tool_calls_after_two_turns():
    llm = IdentifiedLLM(
        [
            ChatMessage(role="assistant", content="Here are the logs..."),
            ChatMessage(role="assistant", content="Let me fetch those logs."),
        ]
    )
    client = MagicMock()
    with pytest.raises(ToolCallingUnsupportedError) as exc_info:
        run_agent("please fetch log lines for myapi", llm=llm, client=client)
    msg = str(exc_info.value)
    assert "deepseek-r1:14b" in msg
    assert "maximum number of tool rounds" not in msg
    assert len(llm.calls) == 2


def test_no_fail_fast_when_second_turn_has_tools():
    client = MagicMock()
    client.containers.list.return_value = []
    client.containers.get.side_effect = _not_found_side_effect
    llm = ScriptedLLM(
        [
            ChatMessage(role="assistant", content="I'll get the logs."),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="get_container_logs",
                        arguments={"target": "pg_tileserv"},
                    )
                ],
            ),
            ChatMessage(role="assistant", content="No logs available."),
        ]
    )
    result = run_agent("please fetch log lines for myapi", llm=llm, client=client)
    assert len(llm.calls) >= 2
    assert any(
        item.get("tool") == "get_container_logs" for item in result.tool_results
    )


def test_shortcut_skips_llm_no_tool_support_check():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="api-server")]
    llm = IdentifiedLLM([])
    result = run_agent("show running containers", llm=llm, client=client)
    assert llm.calls == []
    assert "tool calls" not in (result.answer or "").lower()


def _not_found_side_effect(*_args, **_kwargs):
    from docker.errors import NotFound

    raise NotFound("missing")
