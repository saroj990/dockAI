from dockai.formatting import format_elapsed


def test_format_elapsed_ms():
    assert format_elapsed(0.42) == "420 ms"


def test_format_elapsed_seconds():
    assert format_elapsed(12.34) == "12.3s"


def test_format_elapsed_minutes():
    assert format_elapsed(65.2) == "1m 5.2s"


def test_agent_records_stage_timings():
    from unittest.mock import MagicMock

    from dockai.agent.loop import run_agent
    from dockai.llm.base import ChatMessage, ToolCall
    from tests.conftest import make_container
    from tests.test_agent import ScriptedLLM

    client = MagicMock()
    client.containers.list.return_value = [make_container()]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="1", name="list_containers", arguments={})],
            ),
            ChatMessage(role="assistant", content="done"),
        ]
    )
    result = run_agent("list", llm=llm, client=client)
    labels = [label for label, _ in result.timings]
    assert any(label.startswith("ollama") for label in labels)
    assert any(label.startswith("docker") for label in labels)
