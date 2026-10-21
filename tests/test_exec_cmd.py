"""exec_in_container propose / apply (confirm-gated)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dockai.agent.loop import run_agent
from dockai.llm.base import ChatMessage, ToolCall
from dockai.tools.exec_cmd import apply_exec, propose_exec
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_propose_exec_needs_confirmation(mock_client):
    container = make_container(name="postgis")
    mock_client.containers.list.return_value = [container]
    pending = propose_exec(mock_client, "postgis", "ls -la /tmp")
    assert pending["needs_confirmation"] is True
    assert pending["action"] == "exec"
    assert pending["command"] == "ls -la /tmp"
    assert pending["target"] == "postgis"


def test_propose_exec_blocks_destructive(mock_client):
    mock_client.containers.list.return_value = [make_container(name="postgis")]
    with pytest.raises(ValueError, match="destructive"):
        propose_exec(mock_client, "postgis", "rm -rf /")


def test_apply_exec_runs_command(mock_client):
    container = make_container(name="postgis")
    container.exec_run.return_value = (0, b"ok\n")
    mock_client.containers.list.return_value = [container]
    out = apply_exec(mock_client, "postgis", "echo ok")
    assert out["exit_code"] == 0
    assert "ok" in out["output"]
    container.exec_run.assert_called_once()


def test_agent_exec_returns_pending_confirmation():
    container = make_container(name="postgis")
    client = MagicMock()
    client.containers.list.return_value = [container]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="exec_in_container",
                        arguments={
                            "target": "postgis",
                            "command": "ls -la /var/lib/postgresql/data",
                        },
                    )
                ],
            )
        ]
    )
    result = run_agent(
        "run ls inside postgis",
        llm=llm,
        client=client,
    )
    assert result.pending_action is not None
    assert result.pending_action["action"] == "exec"
    assert result.pending_action["needs_confirmation"] is True
    assert "ls -la" in result.pending_action["command"]
    # Nothing executed yet.
    container.exec_run.assert_not_called()
