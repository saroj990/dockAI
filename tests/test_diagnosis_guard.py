"""Diagnosis must call troubleshoot_container_logs; no invented tool theater."""

from __future__ import annotations

from unittest.mock import MagicMock

from dockai.agent.loop import (
    _is_diagnosis_ask,
    _looks_like_tool_dump,
    _should_nudge_diagnosis,
    run_agent,
)
from dockai.llm.base import ChatMessage, ToolCall
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_is_diagnosis_ask():
    assert _is_diagnosis_ask("why is my pg_tileserv restarting")
    assert _is_diagnosis_ask("what's wrong with postgis?")
    assert not _is_diagnosis_ask("show me logs for pg_tileserv")


def test_fabricated_tool_narrative_detected():
    fake = '''
    **Step 1: Get container logs**
    ```json
    {"ok": true, "tool": "get_container_logs", "data": {}}
    ```
    After fixing the permissions...
    '''
    assert _looks_like_tool_dump(fake)


def test_diagnosis_without_tool_is_nudged():
    assert _should_nudge_diagnosis(
        "why is pg_tileserv restarting",
        collected=[],
        answer="It is a permissions issue.",
    )
    assert not _should_nudge_diagnosis(
        "why is pg_tileserv restarting",
        collected=[
            {
                "tool": "troubleshoot_container_logs",
                "result": {"ok": True, "data": {}},
            }
        ],
        answer="Based on the tool…",
    )


def test_hallucinated_diagnosis_does_not_return_fake_story():
    """Model invents tool JSON with no tool_calls — must not accept that answer."""
    container = make_container(
        name="pg_tileserv",
        status="restarting",
        restarting=True,
        logs=b"FATAL: database connection failed\n",
    )
    client = MagicMock()
    client.containers.list.return_value = [container]

    fake = (
        '```json\n{"ok": true, "tool": "docker_exec", "data": {}}\n```\n'
        "After fixing the permissions, the container started successfully."
    )
    llm = ScriptedLLM(
        [
            ChatMessage(role="assistant", content=fake),
            ChatMessage(role="assistant", content=fake),
            ChatMessage(role="assistant", content=fake),
            ChatMessage(role="assistant", content=fake),
            ChatMessage(role="assistant", content=fake),
            ChatMessage(role="assistant", content=fake),
        ]
    )
    result = run_agent(
        "why is my pg_tileserv restarting",
        llm=llm,
        client=client,
        max_turns=6,
    )
    assert any(
        t["tool"] == "troubleshoot_container_logs" and t["result"].get("ok")
        for t in result.tool_results
    )
    assert "permissions" not in result.answer.lower()
    assert "Docker inspect" in result.answer
    assert len(llm.calls) == 0


def test_diagnosis_with_real_troubleshoot_summarizes():
    container = make_container(
        name="pg_tileserv",
        status="restarting",
        restarting=True,
        logs=b"error: connection refused\n",
    )
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
                        name="troubleshoot_container_logs",
                        arguments={"target": "pg_tileserv"},
                    )
                ],
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "Facts: container is restarting; logs show connection refused. "
                    "Hypothesis: upstream DB unreachable."
                ),
            ),
        ]
    )
    result = run_agent(
        "why is my pg_tileserv restarting",
        llm=llm,
        client=client,
    )
    assert any(
        t["tool"] == "troubleshoot_container_logs" and t["result"].get("ok")
        for t in result.tool_results
    )
    assert "connection refused" in result.answer.lower() or "restarting" in result.answer.lower()
