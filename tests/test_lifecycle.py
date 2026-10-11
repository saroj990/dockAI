from unittest.mock import MagicMock

import pytest

from dockai.agent.confirm import is_affirmative
from dockai.agent.loop import run_agent
from dockai.agent.registry import MUTATING_TOOLS, build_registry, execute_tool
from dockai.llm.base import ChatMessage, ToolCall
from dockai.tools.lifecycle import apply_action, propose_action
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_affirmative_parsing():
    assert is_affirmative("yes") is True
    assert is_affirmative("NO") is False
    assert is_affirmative("maybe") is None


def test_propose_does_not_mutate(mock_client):
    container = make_container(name="api-server", status="running")
    mock_client.containers.list.return_value = [container]
    proposal = propose_action(mock_client, "stop", "api-server")
    assert proposal["needs_confirmation"] is True
    assert proposal["action"] == "stop"
    assert proposal["target"] == "api-server"
    container.stop.assert_not_called()
    container.start.assert_not_called()
    container.restart.assert_not_called()


def test_apply_stop_verifies_state(mock_client):
    container = make_container(name="api-server", status="running")

    def _stop():
        container.attrs["State"]["Status"] = "exited"
        container.status = "exited"

    container.stop.side_effect = _stop
    mock_client.containers.list.return_value = [container]
    outcome = apply_action(mock_client, "stop", "api-server")
    container.stop.assert_called_once()
    assert outcome["before"]["status"] == "running"
    assert outcome["after"]["status"] == "exited"
    assert outcome["needs_confirmation"] is False


def test_llm_tool_only_proposes():
    client = MagicMock()
    container = make_container(name="api-server")
    client.containers.list.return_value = [container]
    result = execute_tool(
        build_registry(),
        client,
        "stop_container",
        {"target": "api-server"},
    )
    assert result["ok"] is True
    assert result["data"]["needs_confirmation"] is True
    container.stop.assert_not_called()
    assert "stop_container" in MUTATING_TOOLS


def test_agent_returns_pending_without_second_llm_round():
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
            ),
            # Would be used only if we incorrectly asked the model again.
            ChatMessage(role="assistant", content="should-not-appear"),
        ]
    )
    result = run_agent("stop api-server", llm=llm, client=client)
    assert result.pending_action is not None
    assert result.pending_action["action"] == "stop"
    assert "Confirm" in result.answer or "confirmation" in result.answer.lower()
    assert result.answer != "should-not-appear"
    assert llm.responses  # second scripted reply unused


def test_unsupported_action():
    with pytest.raises(ValueError):
        propose_action(MagicMock(), "kill", "x")  # type: ignore[arg-type]
