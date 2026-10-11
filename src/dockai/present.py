"""Render structured Docker tool results without a second LLM pass."""

from __future__ import annotations

from typing import Any

from dockai.formatting import (
    console,
    print_containers,
    print_inspect,
    print_logs,
    print_search,
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


def presentation_from_tool(name: str, data: Any) -> dict[str, Any] | None:
    """Build a presentation payload for a successful read tool, or None."""
    if name == "list_containers" and isinstance(data, list):
        return {
            "kind": "containers",
            "caption": f"Showing {len(data)} container(s) from Docker.",
            "rows": data,
            "columns": ["id", "name", "status", "image", "uptime"],
            "title": "Containers",
            "empty_message": "No containers found.",
        }
    if name == "list_uptime" and isinstance(data, dict):
        rows = data.get("containers") or []
        return {
            "kind": "containers",
            "caption": f"Uptime for {len(rows)} container(s) from Docker.",
            "rows": rows,
            "columns": ["id", "name", "status", "uptime"],
            "title": "Container uptime",
            "empty_message": "No containers found.",
        }
    if name == "search_containers" and isinstance(data, dict):
        return {
            "kind": "search",
            "caption": (
                f"Search for '{data.get('keyword')}' "
                f"(scope: {data.get('scope')}) — {data.get('count', 0)} match(es)."
            ),
            "data": data,
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
    return None


def try_table_first(batch: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    If this tool round is one successful table-first tool, return presentation.

    Multi-tool rounds (e.g. restarting + logs) keep the LLM summary path.
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
    return presentation_from_tool(name, result.get("data"))


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
        print_search(presentation["data"])
        return
    if kind == "logs":
        print_logs(presentation["data"])
        return
    if kind == "inspect":
        print_inspect(presentation["data"])
        return
    console.print(presentation.get("caption", ""))
