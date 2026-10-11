"""Controlled tool schemas, validation, and dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import docker

from dockai.errors import DockaiError
from dockai.tools.containers import (
    DEFAULT_LOG_TAIL,
    get_container_logs,
    inspect_container,
    list_containers,
    search_containers,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]


def _require_bool(args: dict[str, Any], key: str, default: bool) -> bool:
    if key not in args or args[key] is None:
        return default
    return _coerce_bool(args[key], key)


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string.")
    return value.strip()


def _optional_int(args: dict[str, Any], key: str) -> int | None:
    if key not in args or args[key] is None:
        return None
    value = _coerce_int(args[key], key)
    if value < 0:
        raise ValueError(f"'{key}' must be >= 0.")
    return value


def _coerce_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValueError(f"'{key}' must be a boolean.")


def _coerce_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"'{key}' must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    raise ValueError(f"'{key}' must be an integer.")


def build_registry() -> dict[str, ToolSpec]:
    return {
        "list_containers": ToolSpec(
            name="list_containers",
            description="List Docker containers. Defaults to running only.",
            parameters={
                "type": "object",
                "properties": {
                    "all_containers": {
                        "type": "boolean",
                        "description": "If true, include stopped containers.",
                    }
                },
                "additionalProperties": False,
            },
            handler=lambda client, **a: list_containers(
                client, all_containers=_require_bool(a, "all_containers", False)
            ),
        ),
        "inspect_container": ToolSpec(
            name="inspect_container",
            description="Inspect one container by name or ID.",
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Container name or ID.",
                    }
                },
                "required": ["target"],
                "additionalProperties": False,
            },
            handler=lambda client, **a: inspect_container(client, _require_str(a, "target")),
        ),
        "get_container_logs": ToolSpec(
            name="get_container_logs",
            description=(
                f"Get container logs. Default last {DEFAULT_LOG_TAIL} lines. "
                "Use full=true for all available logs (may truncate)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Container name or ID."},
                    "tail": {
                        "type": "integer",
                        "description": f"Lines from the end. Default {DEFAULT_LOG_TAIL}.",
                    },
                    "full": {
                        "type": "boolean",
                        "description": "If true, fetch all available logs.",
                    },
                },
                "required": ["target"],
                "additionalProperties": False,
            },
            handler=lambda client, **a: get_container_logs(
                client,
                _require_str(a, "target"),
                tail=_optional_int(a, "tail"),
                full=_require_bool(a, "full", False),
            ),
        ),
        "search_containers": ToolSpec(
            name="search_containers",
            description="Case-insensitive container name keyword search (default: all containers).",
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Name keyword."},
                    "running_only": {
                        "type": "boolean",
                        "description": "If true, search running containers only.",
                    },
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
            handler=lambda client, **a: search_containers(
                client,
                _require_str(a, "keyword"),
                running_only=_require_bool(a, "running_only", False),
            ),
        ),
        "list_uptime": ToolSpec(
            name="list_uptime",
            description="List containers with uptime/state derived from Docker start times.",
            parameters={
                "type": "object",
                "properties": {
                    "all_containers": {
                        "type": "boolean",
                        "description": "If true, include stopped containers.",
                    }
                },
                "additionalProperties": False,
            },
            handler=lambda client, **a: {
                "containers": list_containers(
                    client, all_containers=_require_bool(a, "all_containers", False)
                )
            },
        ),
    }


def ollama_tool_schemas(registry: dict[str, ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in registry.values()
    ]


def execute_tool(
    registry: dict[str, ToolSpec],
    client: docker.DockerClient,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Validate and run a tool. Never invent Docker facts on failure."""
    if "__invalid__" in arguments:
        return {
            "ok": False,
            "error": "Invalid tool arguments: could not parse JSON object.",
        }
    spec = registry.get(name)
    if spec is None:
        return {"ok": False, "error": f"Unknown tool '{name}'. Allowed: {sorted(registry)}"}
    unknown = set(arguments) - set(spec.parameters.get("properties", {}))
    if unknown:
        return {"ok": False, "error": f"Unexpected arguments: {sorted(unknown)}"}
    required = set(spec.parameters.get("required") or [])
    missing = required - set(arguments)
    if missing:
        return {"ok": False, "error": f"Missing required arguments: {sorted(missing)}"}
    try:
        data = spec.handler(client, **arguments)
        return {"ok": True, "tool": name, "data": data}
    except DockaiError as exc:
        return {"ok": False, "error": str(exc)}
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "hint": (
                "Retry via the tool interface with JSON types: "
                'integers like 25 (not "25"), booleans like false (not "false"). '
                "Do not print tool JSON to the user."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Tool execution failed: {exc}"}
