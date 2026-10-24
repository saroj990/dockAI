"""Fuzzy / phonetic container name matching."""

from __future__ import annotations

from unittest.mock import MagicMock

from dockai.agent.intent import extract_diagnose_container_target, resolve_intent
from dockai.agent.target_match import (
    pick_best_container_name,
    refine_tool_target,
    similarity_score,
)
from tests.conftest import make_container


def test_similarity_tileserv_typo():
    assert similarity_score("pg tilserv", "pg_tileserv") >= 0.84
    assert pick_best_container_name(
        "pg tilserv", ["pg_tileserv", "postgis"]
    ) == "pg_tileserv"


def test_pick_best_prefers_focus_at_lower_threshold():
    assert (
        pick_best_container_name(
            "pg tilserv",
            ["pg_tileserv", "pg_tileserv_backup"],
            focus="pg_tileserv",
        )
        == "pg_tileserv"
    )


def test_intent_issues_typo_with_focus():
    m = resolve_intent(
        "why my pg tilserv showing issues",
        focus_container="pg_tileserv",
    )
    assert m.tool == "troubleshoot_container_logs"
    assert m.arguments["target"] == "pg_tileserv"


def test_refine_tool_target_uses_docker_names(mock_client):
    mock_client.containers.list.return_value = [
        make_container(name="pg_tileserv"),
        make_container(name="postgis"),
    ]
    args = refine_tool_target(
        mock_client,
        {"target": "pg tilserv"},
        focus_container="pg_tileserv",
    )
    assert args["target"] == "pg_tileserv"


def test_extract_diagnose_without_focus_still_parses_name():
    target = extract_diagnose_container_target("is my pg_tileserv restarting")
    assert target == "pg_tileserv"
