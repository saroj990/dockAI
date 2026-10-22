"""Deterministic diagnosis facts and log summaries from troubleshoot data."""

from __future__ import annotations

from unittest.mock import MagicMock

from dockai.agent.loop import run_agent
from dockai.diagnosis_summary import (
    build_diagnosis_answer,
    is_active_restart_loop,
    should_finish_diagnosis_without_llm,
    summarize_log_issues,
    validate_status_for_troubleshoot,
)
from dockai.llm.base import ChatMessage, ToolCall
from dockai.tools.troubleshoot import troubleshoot_container_logs
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def _troubleshoot_payload(
    *,
    restarting: bool = False,
    restarts: int = 0,
    status: str = "running",
    logs: str = "",
) -> dict:
    analysis = {
        "highlight_lines": [],
        "categories": [],
        "signal_line_count": 0,
        "has_traceback": False,
    }
    if logs:
        from dockai.tools.troubleshoot import analyze_log_text

        analysis = analyze_log_text(logs)
    return {
        "container": "timescaledb",
        "id": "abc123",
        "inspect": {
            "name": "timescaledb",
            "status": status,
            "restarts": restarts,
            "restarting": restarting,
            "health": "healthy",
            "uptime": {"label": "Uptime", "value": "1h 46m 13s"},
            "exit_code": 0,
            "oom_killed": False,
        },
        "status_validation": validate_status_for_troubleshoot(
            {
                "status": status,
                "restarts": restarts,
                "restarting": restarting,
            }
        ),
        "analysis": analysis,
    }


def test_fact_lead_restart_premise_not_restarting():
    data = _troubleshoot_payload(
        restarting=False,
        restarts=0,
        logs="2026-10-17 ERROR: function postgis_version() does not exist\n",
    )
    answer = build_diagnosis_answer("why is my timescaledb restarting", data)
    assert "does not show an active restart loop" in answer
    assert "Restarts: 0" in answer
    assert "Restarting: False" in answer
    assert should_finish_diagnosis_without_llm("why is timescaledb restarting", data)


def test_fact_lead_actual_restart_loop():
    data = _troubleshoot_payload(
        restarting=True,
        restarts=5,
        status="restarting",
        logs="panic: oom\n",
    )
    answer = build_diagnosis_answer("why is api restarting", data)
    assert "restart problem" in answer.lower()
    assert is_active_restart_loop(data["inspect"])
    assert not should_finish_diagnosis_without_llm("why is api restarting", data)


def test_summarize_log_issues_postgis_and_shutdown():
    data = _troubleshoot_payload(
        logs=(
            "FATAL: terminating background worker due to administrator command\n"
            "ERROR: function postgis_version() does not exist\n"
        ),
    )
    summary = summarize_log_issues(data["analysis"], inspect=data["inspect"])
    assert "PostGIS" in summary or "postgis" in summary.lower()
    assert "Log scan" in summary


def test_troubleshoot_includes_status_validation_before_logs(mock_client):
    container = make_container(name="timescaledb", restart_count=0, restarting=False)
    mock_client.containers.list.return_value = [container]
    data = troubleshoot_container_logs(mock_client, "timescaledb", tail=20)
    assert "status_validation" in data
    assert data["status_validation"]["active_restart_loop"] is False
    assert data["inspect"]["restarts"] == 0
    container.logs.assert_called()


def test_run_agent_premise_mismatch_skips_llm_summary():
    container = make_container(
        name="timescaledb",
        restart_count=0,
        restarting=False,
        logs=b"ERROR: function postgis_version() does not exist\n",
    )
    client = MagicMock()
    client.containers.list.return_value = [container]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="troubleshoot_container_logs",
                        arguments={"target": "timescaledb"},
                    )
                ],
            ),
            ChatMessage(
                role="assistant",
                content="Should not reach this LLM summary.",
            ),
        ]
    )
    result = run_agent(
        "why is my timescaledb restarting",
        llm=llm,
        client=client,
    )
    assert any(
        t["tool"] == "troubleshoot_container_logs" and t["result"].get("ok")
        for t in result.tool_results
    )
    assert "does not show an active restart loop" in result.answer
    assert "Log scan" in result.answer
    assert len(llm.calls) == 1


def test_run_agent_active_restart_prepends_facts_before_llm():
    container = make_container(
        name="api-server",
        status="restarting",
        restarting=True,
        restart_count=2,
        logs=b"Error: connection refused\n",
    )
    client = MagicMock()
    client.containers.list.return_value = [container]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="troubleshoot_container_logs",
                        arguments={"target": "api-server"},
                    )
                ],
            ),
            ChatMessage(
                role="assistant",
                content="Hypothesis: upstream service is down.",
            ),
        ]
    )
    result = run_agent(
        "why is api-server restarting",
        llm=llm,
        client=client,
    )
    assert "Docker inspect for api-server" in result.answer
    assert "restart problem" in result.answer.lower()
    assert "Hypothesis" in result.answer
    assert len(llm.calls) == 2


def test_multi_tool_batch_troubleshoot_gets_fact_lead():
    container = make_container(
        name="timescaledb",
        restart_count=0,
        restarting=False,
        logs=b"ERROR: db error\n",
    )
    client = MagicMock()
    client.containers.list.return_value = [container]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="list_restarting_containers",
                        arguments={},
                    ),
                    ToolCall(
                        id="2",
                        name="troubleshoot_container_logs",
                        arguments={"target": "timescaledb"},
                    ),
                ],
            ),
            ChatMessage(role="assistant", content="unused"),
        ]
    )
    result = run_agent(
        "why is timescaledb restarting",
        llm=llm,
        client=client,
    )
    assert "does not show an active restart loop" in result.answer
    assert any(t["tool"] == "troubleshoot_container_logs" for t in result.tool_results)
