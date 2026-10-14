from dockai.columns import (
    coerce_columns_arg,
    parse_columns_from_text,
    resolve_columns,
)
from dockai.present import try_table_first


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
