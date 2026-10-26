"""Local-first intent resolution (normalize → classify → slots)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from dockai.agent.intent import (
    normalize_diagnose_text,
    normalize_intent_text,
    resolve_intent,
)
from dockai.agent.loop import run_agent
from dockai.agent.shortcuts import match_shortcut
from dockai.llm.base import ChatMessage
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Show me logs for pg_tileserv", "logs for pg_tileserv"),
        ("can we see logs for pg_tileserv", "logs for pg_tileserv"),
        ("can we have logs for pg tileserv", "logs for pg tileserv"),
        ("can you please restart the container named api-server", "restart the container named api-server"),
        ("show me running containers", "running containers"),
        ("  dig into the logs for x  ", "logs for x"),
    ],
)
def test_normalize_intent_text(raw: str, expected: str):
    assert normalize_intent_text(raw).lower() == expected.lower()


@pytest.mark.parametrize(
    "phrase,tool,target,tail",
    [
        ("logs for pg_tileserv", "get_container_logs", "pg_tileserv", None),
        ("show me logs for pg_tileserv", "get_container_logs", "pg_tileserv", None),
        ("can we see logs for pg_tileserv", "get_container_logs", "pg_tileserv", None),
        ("can we have logs for pg tileserv", "get_container_logs", "pg tileserv", None),
        ("can we see the logs for pg_tileserv", "get_container_logs", "pg_tileserv", None),
        ("let me see logs for pg_tileserv", "get_container_logs", "pg_tileserv", None),
        ("I want to see logs for pg tileserv", "get_container_logs", "pg tileserv", None),
        (
            "show me logs for pg_tileserv containers",
            "get_container_logs",
            "pg_tileserv",
            None,
        ),
        (
            "dig into the logs for saien backend api",
            "get_container_logs",
            "saien backend api",
            None,
        ),
        (
            "show last 25 lines of api-server logs",
            "get_container_logs",
            "api-server",
            25,
        ),
        (
            "api-server logs for last 150 lines",
            "get_container_logs",
            "api-server",
            150,
        ),
        ("can we dig into the logs for saien backend api", "get_container_logs", "saien backend api", None),
    ],
)
def test_intent_logs_phrases(phrase: str, tool: str, target: str, tail: int | None):
    m = resolve_intent(phrase)
    assert m.tool == tool
    assert m.confidence >= 0.8
    assert m.arguments["target"] == target
    if tail is None:
        assert "tail" not in m.arguments
    else:
        assert m.arguments["tail"] == tail
    assert match_shortcut(phrase) is not None


@pytest.mark.parametrize(
    "phrase,target",
    [
        ("why is my pg tileserv restarting", "pg tileserv"),
        ("why is pg_tileserv restarting", "pg_tileserv"),
        ("why does my api-server keep crashing", "api-server"),
        ("is my pg tileserv restarting", "pg tileserv"),
        ("is pg_tileserv restarting", "pg_tileserv"),
        (
            "hey can you tell me if my docker container pg tileserv "
            "is still restarting right now please?",
            "pg tileserv",
        ),
        (
            "I'm wondering whether pg_tileserv keeps crashing again",
            "pg_tileserv",
        ),
        (
            "quick question: is the pg tileserv container restarting",
            "pg tileserv",
        ),
        ("my pg tileserv is restarting", "pg tileserv"),
    ],
)
def test_intent_diagnose_restart_phrases(phrase: str, target: str):
    m = resolve_intent(phrase)
    assert m.tool == "troubleshoot_container_logs"
    assert m.confidence >= 0.8
    assert m.arguments["target"] == target
    assert match_shortcut(phrase) is not None


def test_intent_diagnose_restart_focused():
    m = resolve_intent("why is it restarting", focus_container="pg_tileserv")
    assert m.tool == "troubleshoot_container_logs"
    assert m.arguments["target"] == "pg_tileserv"
    m2 = resolve_intent("is it restarting", focus_container="pg_tileserv")
    assert m2.arguments["target"] == "pg_tileserv"


def test_normalize_diagnose_text_strips_vernacular():
    assert normalize_diagnose_text(
        "Hey, can you please tell me if my docker container pg tileserv "
        "is still restarting right now?"
    ) == "is pg tileserv restarting"


def test_reconcile_troubleshoot_placeholder_target():
    from dockai.agent.intent import reconcile_troubleshoot_target

    args = reconcile_troubleshoot_target(
        "is my pg tileserv restarting",
        "troubleshoot_container_logs",
        {"target": "<container-name-or-id>"},
    )
    assert args["target"] == "pg tileserv"


@pytest.mark.parametrize(
    "phrase,tool",
    [
        ("show me running containers", "list_containers"),
        ("show running containers", "list_containers"),
        ("list all containers", "list_containers"),
        ("show me uptime of running containers", "list_uptime"),
        ("only name and uptime of running containers", "list_uptime"),
        ("stop pg_tileserv", "stop_container"),
        ("can you restart container with name postgis", "restart_container"),
        ("please start api-server", "start_container"),
        ("inspect postgis", "inspect_container"),
        ("show me details for postgis", "inspect_container"),
        ("find containers named flink", "search_containers"),
    ],
)
def test_intent_other_actions(phrase: str, tool: str):
    m = resolve_intent(phrase)
    assert m.tool == tool
    assert m.confidence >= 0.8
    s = match_shortcut(phrase)
    assert s is not None
    assert s.tool == tool


@pytest.mark.parametrize(
    "phrase",
    [
        "what could be wrong with postgis?",
        "why are the logs for pg_tileserv failing?",
        "help me understand these logs",
    ],
)
def test_intent_troubleshoot_goes_to_llm(phrase: str):
    m = resolve_intent(phrase)
    assert m.tool is None
    assert m.confidence < 0.8
    assert match_shortcut(phrase) is None


def test_intent_focused_logs():
    m = resolve_intent("show its last 25 log lines", focus_container="saien-backend-api")
    assert m.tool == "get_container_logs"
    assert m.arguments["target"] == "saien-backend-api"
    assert m.arguments["tail"] == 25


def test_show_me_logs_skips_ollama_in_agent():
    client = MagicMock()
    client.containers.list.return_value = [
        make_container(name="pg_tileserv", logs=b"tile error\n")
    ]
    llm = ScriptedLLM(
        [ChatMessage(role="assistant", content="should-not-be-called")]
    )
    result = run_agent(
        "show me logs for pg_tileserv",
        llm=llm,
        client=client,
    )
    assert result.presentation is not None
    assert result.presentation["kind"] == "logs"
    assert any(label == "shortcut:logs" for label, _ in result.timings)
    assert not any(label.startswith("ollama") for label, _ in result.timings)
