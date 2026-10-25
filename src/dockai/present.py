"""Render structured Docker tool results without a second LLM pass."""

from __future__ import annotations

from typing import Any

from dockai.columns import resolve_columns
from rich.markdown import Markdown

from dockai.formatting import (
    console,
    print_containers,
    print_inspect,
    print_logs,
    print_search,
    print_troubleshoot,
)

# Single-tool reads that are clear without model narration.
TABLE_FIRST_TOOLS = frozenset(
    {
        "list_containers",
        "list_uptime",
        "search_containers",
        "get_container_logs",
        "inspect_container",
    }
)

_DEFAULT_COLUMNS = {
    "list_containers": ["id", "name", "status", "image", "uptime"],
    "list_uptime": ["id", "name", "status", "uptime"],
    "search_containers": ["id", "name", "status", "image", "uptime"],
}


def presentation_from_tool(
    name: str,
    data: Any,
    *,
    user_text: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a presentation payload for a successful read tool, or None."""
    if name == "list_containers" and isinstance(data, list):
        columns = resolve_columns(
            user_text=user_text,
            tool_arguments=tool_arguments,
            default=_DEFAULT_COLUMNS["list_containers"],
        )
        return {
            "kind": "containers",
            "caption": f"Showing {len(data)} container(s) from Docker.",
            "rows": data,
            "columns": columns,
            "title": "Containers",
            "empty_message": "No containers found.",
        }
    if name == "list_uptime" and isinstance(data, dict):
        rows = data.get("containers") or []
        columns = resolve_columns(
            user_text=user_text,
            tool_arguments=tool_arguments,
            default=_DEFAULT_COLUMNS["list_uptime"],
        )
        return {
            "kind": "containers",
            "caption": f"Uptime for {len(rows)} container(s) from Docker.",
            "rows": rows,
            "columns": columns,
            "title": "Container uptime",
            "empty_message": "No containers found.",
        }
    if name == "search_containers" and isinstance(data, dict):
        columns = resolve_columns(
            user_text=user_text,
            tool_arguments=tool_arguments,
            default=_DEFAULT_COLUMNS["search_containers"],
        )
        return {
            "kind": "search",
            "caption": (
                f"Search for '{data.get('keyword')}' "
                f"(scope: {data.get('scope')}) — {data.get('count', 0)} match(es)."
            ),
            "data": data,
            "columns": columns,
        }
    if name == "get_container_logs" and isinstance(data, dict):
        return {
            "kind": "logs",
            "caption": (
                f"Logs for {data.get('container')} ({data.get('id')}) — {data.get('note')}"
            ),
            "data": data,
        }
    if name == "inspect_container" and isinstance(data, dict):
        return {
            "kind": "inspect",
            "caption": f"Inspect {data.get('name')} ({data.get('id')}) from Docker.",
            "data": data,
        }
    if name == "troubleshoot_container_logs" and isinstance(data, dict):
        signals = (data.get("analysis") or {}).get("signal_line_count", 0)
        return {
            "kind": "troubleshoot_logs",
            "caption": (
                f"Troubleshoot evidence for {data.get('container')} "
                f"({data.get('id')}) — {signals} log signal line(s) from Docker."
            ),
            "data": data,
        }
    return None


def try_table_first(
    batch: list[dict[str, Any]],
    *,
    user_text: str | None = None,
) -> dict[str, Any] | None:
    """
    If this tool round is one successful table-first tool, return presentation.

    Multi-tool rounds (e.g. restarting + logs) keep the LLM summary path.
    Column intent comes from tool args and/or the user message.
    """
    if len(batch) != 1:
        return None
    item = batch[0]
    result = item.get("result") or {}
    if not result.get("ok"):
        return None
    name = item.get("tool") or ""
    if name not in TABLE_FIRST_TOOLS:
        return None
    return presentation_from_tool(
        name,
        result.get("data"),
        user_text=user_text,
        tool_arguments=item.get("arguments") if isinstance(item.get("arguments"), dict) else None,
    )


def render_presentation(presentation: dict[str, Any]) -> None:
    """Print Rich output grounded in Docker tool data."""
    kind = presentation.get("kind")
    if kind == "containers":
        print_containers(
            presentation.get("rows") or [],
            columns=presentation.get("columns"),
            title=presentation.get("title"),
            empty_message=presentation.get("empty_message", "No containers found."),
        )
        return
    if kind == "search":
        print_search(
            presentation["data"],
            columns=presentation.get("columns"),
        )
        return
    if kind == "logs":
        print_logs(presentation["data"])
        return
    if kind == "inspect":
        print_inspect(presentation["data"])
        return
    if kind == "troubleshoot_logs":
        print_troubleshoot(presentation["data"])
        return
    if kind == "help":
        console.print(Markdown(presentation.get("markdown") or ""))
        return
    console.print(presentation.get("caption", ""))
