"""NL status filtering: inactive, not running, stopped, and follow-ups."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dockai.agent.loop import run_agent
from dockai.agent.scope import (
    apply_list_scope,
    detect_status_filter,
    effective_list_user_text,
    reconcile_tool_for_list_intent,
)
from dockai.agent.session import ChatSession
from dockai.agent.shortcuts import match_shortcut
from dockai.llm.base import ChatMessage, ToolCall
from dockai.tools.containers import list_containers
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def _mock_client_with_mixed():
    client = MagicMock()
    client.containers.list.return_value = [
        make_container(name="api-server", status="running", cid="a" * 64),
        make_container(name="old-job", status="exited", cid="b" * 64),
        make_container(name="fresh", status="created", cid="c" * 64),
        make_container(name="ghost", status="dead", cid="d" * 64),
    ]
    return client


@pytest.mark.parametrize(
    "phrase",
    [
        "Show me inactive containers.",
        "Show me containers that are not running.",
        "show me containers which not running right now",
        "Show me stopped containers.",
        "List all containers except running ones.",
    ],
)
def test_detect_status_not_name_search(phrase: str):
    assert detect_status_filter(phrase) in {"not_running", "stopped"}
    shortcut = match_shortcut(phrase)
    assert shortcut is not None
    assert shortcut.tool == "list_containers"
    assert shortcut.tool != "search_containers"


def test_inactive_search_redirects_to_list():
    tool, args = reconcile_tool_for_list_intent(
        "show me inactive containers",
        "search_containers",
        {"keyword": "inactive", "running_only": False},
    )
    assert tool == "list_containers"
    assert args["status"] == "not_running"
    assert args["all_containers"] is True


def test_not_running_excludes_running_rows():
    client = _mock_client_with_mixed()
    rows = list_containers(client, all_containers=True, status="not_running")
    names = {row["name"] for row in rows}
    assert "api-server" not in names
    assert "old-job" in names
    assert "fresh" in names
    assert "ghost" in names
    assert all(row["status"] != "running" for row in rows)


def test_stopped_filter_excludes_running():
    client = _mock_client_with_mixed()
    rows = list_containers(client, all_containers=True, status="stopped")
    assert all(row["status"] in {"exited", "dead"} for row in rows)
    assert not any(row["name"] == "api-server" for row in rows)


def test_unfiltered_all_containers_unchanged():
    client = _mock_client_with_mixed()
    rows = list_containers(client, all_containers=True)
    assert len(rows) == 4


def test_shortcut_inactive_via_agent():
    client = _mock_client_with_mixed()
    llm = ScriptedLLM([ChatMessage(role="assistant", content="should-not-run")])
    result = run_agent("show me inactive containers", llm=llm, client=client)
    assert result.presentation is not None
    rows = result.presentation["rows"]
    assert all(row["status"] != "running" for row in rows)
    assert any(row["name"] == "old-job" for row in rows)


def test_llm_search_inactive_redirects_to_filtered_list():
    client = _mock_client_with_mixed()
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="search_containers",
                        arguments={"keyword": "inactive", "running_only": False},
                    )
                ],
            ),
        ]
    )
    result = run_agent("show me inactive containers", llm=llm, client=client)
    assert result.tool_results[0]["tool"] == "list_containers"
    assert result.tool_results[0]["arguments"]["status"] == "not_running"
    rows = result.presentation["rows"]
    assert all(row["status"] != "running" for row in rows)


def test_session_follow_up_not_running_uses_list_context():
    client = _mock_client_with_mixed()
    llm = ScriptedLLM(
        [
            ChatMessage(role="assistant", content="should-not-run"),
            ChatMessage(role="assistant", content="should-not-run"),
        ]
    )
    session = ChatSession(llm=llm, client=client)
    first = session.ask("show me all containers")
    assert first.presentation is not None
    assert len(first.presentation["rows"]) == 4

    second = session.ask("not running")
    assert second.presentation is not None
    rows = second.presentation["rows"]
    assert all(row["status"] != "running" for row in rows)
    assert session.last_list_user_text == "show me all containers"


def test_effective_list_user_text_merges_follow_up():
    merged = effective_list_user_text(
        "not running",
        "show me containers which not running right now",
    )
    assert detect_status_filter(merged) == "not_running"


def test_apply_list_scope_not_running_overrides_model():
    forced = apply_list_scope(
        "containers which not running right now",
        "list_containers",
        {"all_containers": False},
    )
    assert forced["all_containers"] is True
    assert forced["status"] == "not_running"
