from unittest.mock import MagicMock

from dockai.agent.loop import run_agent
from dockai.agent.policy import check_restricted_request
from dockai.llm.base import ChatMessage, ToolCall
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_delete_container_is_restricted():
    hit = check_restricted_request("can you delete a container")
    assert hit is not None
    assert hit.kind == "delete_container"
    assert "Not supported" in hit.message
    assert "will not stop" in hit.message.lower()


def test_docker_desktop_is_restricted():
    hit = check_restricted_request("stop docker desktop")
    assert hit is not None
    assert hit.kind == "docker_desktop"
    assert "Docker Desktop" in hit.message


def test_normal_stop_not_restricted():
    assert check_restricted_request("stop saien-backend-api") is None
    assert check_restricted_request("show running containers") is None


def test_agent_refuses_delete_without_calling_stop():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="saien-backend-api")]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="stop_container",
                        arguments={"target": "saien-backend-api"},
                    )
                ],
            )
        ]
    )
    result = run_agent(
        "can you delete a container",
        llm=llm,
        client=client,
        focus_container="saien-backend-api",
    )
    assert result.pending_action is None
    assert "Not supported" in result.answer
    assert llm.responses  # model never consulted
    client.containers.list.assert_not_called()
