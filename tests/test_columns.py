from unittest.mock import MagicMock

import pytest

from dockai.agent.loop import run_agent
from dockai.columns import (
    coerce_columns_arg,
    parse_columns_from_text,
    resolve_columns,
    unknown_columns_in_user_text,
    validate_user_column_request,
)
from dockai.llm.base import ChatMessage, ToolCall
from dockai.present import try_table_first
from tests.conftest import make_container
from tests.test_agent import ScriptedLLM


def test_parse_only_name_and_uptime():
    cols = parse_columns_from_text(
        "can you pull only name and uptime of running containers"
    )
    assert cols == ["name", "uptime"]


def test_parse_id_status_name_table():
    cols = parse_columns_from_text("Show ID, status, and name in a table.")
    assert cols == ["id", "status", "name"]


def test_parse_ignores_weak_single_column():
    assert parse_columns_from_text("show containers named flink") is None


def test_coerce_columns_from_llm_string():
    assert coerce_columns_arg("name, uptime") == ["name", "uptime"]
    assert coerce_columns_arg(["Name", "Uptime"]) == ["name", "uptime"]


def test_resolve_prefers_tool_args_over_text():
    cols = resolve_columns(
        user_text="only name and uptime",
        tool_arguments={"columns": ["id", "name"]},
        default=["id", "name", "status"],
    )
    assert cols == ["id", "name"]


def test_resolve_falls_back_to_user_text():
    cols = resolve_columns(
        user_text="only name and uptime",
        tool_arguments={},
        default=["id", "name", "status", "image", "uptime"],
    )
    assert cols == ["name", "uptime"]


def test_table_first_applies_user_columns():
    batch = [
        {
            "tool": "list_containers",
            "arguments": {},
            "result": {
                "ok": True,
                "data": [
                    {
                        "id": "abc",
                        "name": "api",
                        "status": "running",
                        "image": "nginx",
                        "uptime": {"kind": "uptime", "value": "1h"},
                    }
                ],
            },
        }
    ]
    pres = try_table_first(
        batch,
        user_text="can you pull only name and uptime of running containers",
    )
    assert pres is not None
    assert pres["columns"] == ["name", "uptime"]


def test_coerce_columns_strict_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown column name\\(s\\): memory"):
        coerce_columns_arg(["name", "memory"], strict=True)


def test_coerce_columns_strict_lists_supported():
    with pytest.raises(ValueError, match="Supported columns: id, name"):
        coerce_columns_arg(["foobar"], strict=True)


def test_unknown_columns_in_only_phrase():
    bad = unknown_columns_in_user_text(
        "only name and memory of running containers"
    )
    assert bad == ["memory"]


def test_validate_user_column_request_raises():
    with pytest.raises(ValueError, match="memory"):
        validate_user_column_request(
            "can you pull only name and memory of running containers"
        )


def test_agent_at07_table_columns_via_llm_path():
    client = MagicMock()
    client.containers.list.return_value = [make_container(name="api-server")]
    llm = ScriptedLLM(
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="1", name="list_containers", arguments={}),
                ],
            ),
        ]
    )
    result = run_agent(
        "Show ID, status, and name in a table.",
        llm=llm,
        client=client,
    )
    assert result.presentation is not None
    assert result.presentation["columns"] == ["id", "status", "name"]


def test_agent_name_uptime_running_via_shortcut():
    running = make_container(name="api-server", status="running")
    exited = make_container(name="old-job", status="exited", cid="b" * 64)
    client = MagicMock()
    client.containers.list.side_effect = lambda all=False, **_: (
        [running] if not all else [running, exited]
    )
    llm = ScriptedLLM([ChatMessage(role="assistant", content="should-not-run")])
    result = run_agent(
        "can you pull only name and uptime of running containers",
        llm=llm,
        client=client,
    )
    assert result.presentation is not None
    assert result.presentation["columns"] == ["name", "uptime"]
    assert len(result.presentation["rows"]) == 1
    assert result.presentation["rows"][0]["name"] == "api-server"


def test_table_first_uses_tool_column_args():
    batch = [
        {
            "tool": "list_uptime",
            "arguments": {"columns": ["name", "uptime"]},
            "result": {
                "ok": True,
                "data": {"containers": [{"name": "api", "uptime": {"kind": "uptime", "value": "1s"}}]},
            },
        }
    ]
    pres = try_table_first(batch, user_text="show uptime")
    assert pres is not None
    assert pres["columns"] == ["name", "uptime"]
