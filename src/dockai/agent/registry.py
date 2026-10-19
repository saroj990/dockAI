"""Controlled tool schemas, validation, and dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import docker

from dockai.columns import SUPPORTED_COLUMNS, coerce_columns_arg
from dockai.diagnostics import log_tool_call, log_tool_result
from dockai.errors import DockaiError
from dockai.tools.containers import (
    DEFAULT_LOG_TAIL,
    STATUS_FILTERS,
    get_container_logs,
    inspect_container,
    list_containers,
    restarting_containers,
    search_containers,
)
from dockai.tools.lifecycle import Action, propose_action

_COLUMNS_PARAM = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Optional table columns to display. "
        f"Allowed: {', '.join(SUPPORTED_COLUMNS)}. "
        "Use when the user asks for specific fields (e.g. only name and uptime)."
    ),
}


def _validate_optional_columns(args: dict[str, Any]) -> None:
    if "columns" not in args or args["columns"] is None:
        return
    if coerce_columns_arg(args["columns"], strict=True) is None:
        raise ValueError(
            f"'columns' must include at least one supported column: "
            f"{', '.join(SUPPORTED_COLUMNS)}"
        )


def _optional_status(args: dict[str, Any]) -> str | None:
    if "status" not in args or args["status"] is None:
        return None
    value = args["status"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("'status' must be a non-empty string.")
    status = value.strip().lower()
    if status not in STATUS_FILTERS:
        raise ValueError(
            f"'status' must be one of: {', '.join(sorted(STATUS_FILTERS))}."
        )
    return status


_STATUS_PARAM = {
    "type": "string",
    "description": (
        "Optional status filter: running, exited, stopped, or dead. "
        "Use exited/stopped/dead when the user asks for those containers "
        "(requires all_containers=true). stopped matches exited+dead."
    ),
}


def _list_containers_result(client: Any, args: dict[str, Any]) -> Any:
    _validate_optional_columns(args)
    return list_containers(
        client,
        all_containers=_require_bool(args, "all_containers", False),
        status=_optional_status(args),
    )


def _list_uptime_result(client: Any, args: dict[str, Any]) -> Any:
    _validate_optional_columns(args)
    return {
        "containers": list_containers(
            client,
            all_containers=_require_bool(args, "all_containers", False),
            status=_optional_status(args),
        )
    }


def _search_containers_result(client: Any, args: dict[str, Any]) -> Any:
    _validate_optional_columns(args)
    return search_containers(
        client,
        _require_str(args, "keyword"),
        running_only=_require_bool(args, "running_only", False),
        status=_optional_status(args),
    )

MUTATING_TOOLS = frozenset(
    {"start_container", "stop_container", "restart_container"}
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
            description=(
                "List Docker containers. Defaults to running only "
                "(all_containers=false). For 'exited/stopped/dead containers', "
                "set all_containers=true and status=exited|stopped|dead "
                "(otherwise running containers are included). "
                "When the user asks for specific columns, pass them in columns. "
                "Do not use logs/inspect for a plain list."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "all_containers": {
                        "type": "boolean",
                        "description": (
                            "If true, include non-running containers in the Docker "
                            "query. Keep false for running-only. Set true for "
                            "all/stopped/exited asks (pair with status when "
                            "filtering to exited/stopped/dead)."
                        ),
                    },
                    "status": _STATUS_PARAM,
                    "columns": _COLUMNS_PARAM,
                },
                "additionalProperties": False,
            },
            handler=lambda client, **a: _list_containers_result(client, a),
        ),
        "inspect_container": ToolSpec(
            name="inspect_container",
            description=(
                "Inspect one container's metadata and state by name or ID. "
                "Do not use for log output — use get_container_logs instead."
            ),
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
                f"Get container logs (show/tail/dig into logs). Default last "
                f"{DEFAULT_LOG_TAIL} lines. Use full=true for all available logs "
                "(may truncate). Prefer this over inspect_container when the user "
                "asks for logs, log lines, or tail output."
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
                        "description": (
                            "If true, search running containers only. "
                            "Set true when the user asks for running containers."
                        ),
                    },
                    "status": _STATUS_PARAM,
                    "columns": _COLUMNS_PARAM,
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
            handler=lambda client, **a: _search_containers_result(client, a),
        ),
        "list_uptime": ToolSpec(
            name="list_uptime",
            description=(
                "List containers with uptime/state derived from Docker start times. "
                "Defaults to running only. For exited/stopped lists, set "
                "all_containers=true and status accordingly. Pass columns when "
                "the user asks for specific fields."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "all_containers": {
                        "type": "boolean",
                        "description": (
                            "If true, include non-running containers in the query. "
                            "Keep false for running-only. Pair with status for "
                            "exited/stopped/dead filters."
                        ),
                    },
                    "status": _STATUS_PARAM,
                    "columns": _COLUMNS_PARAM,
                },
                "additionalProperties": False,
            },
            handler=lambda client, **a: _list_uptime_result(client, a),
        ),
        "list_restarting_containers": ToolSpec(
            name="list_restarting_containers",
            description=(
                "List containers that are restarting or have a non-zero restart count. "
                "Use for troubleshooting restart loops, then inspect and fetch logs."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=lambda client, **_a: {
                "containers": restarting_containers(client)
            },
        ),
        **_mutation_specs(),
    }


def _mutation_specs() -> dict[str, ToolSpec]:
    """Mutating tools only propose; the CLI applies after user confirmation."""

    def _handler(action: Action) -> Callable[..., Any]:
        return lambda client, **a: propose_action(
            client, action, _require_str(a, "target")
        )

    specs: dict[str, ToolSpec] = {}
    for action in ("start", "stop", "restart"):
        name = f"{action}_container"
        specs[name] = ToolSpec(
            name=name,
            description=(
                f"Propose to {action} a container. Does not change state until the "
                "user confirms in the CLI. Always call this for user requests to "
                f"{action} a container."
            ),
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
            handler=_handler(action),  # type: ignore[arg-type]
        )
    return specs


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
    log_tool_call(name, arguments)
    if "__invalid__" in arguments:
        result = {
            "ok": False,
            "error": "Invalid tool arguments: could not parse JSON object.",
        }
        log_tool_result(name, result)
        return result
    spec = registry.get(name)
    if spec is None:
        result = {"ok": False, "error": f"Unknown tool '{name}'. Allowed: {sorted(registry)}"}
        log_tool_result(name, result)
        return result
    unknown = set(arguments) - set(spec.parameters.get("properties", {}))
    if unknown:
        result = {"ok": False, "error": f"Unexpected arguments: {sorted(unknown)}"}
        log_tool_result(name, result)
        return result
    required = set(spec.parameters.get("required") or [])
    missing = required - set(arguments)
    if missing:
        result = {"ok": False, "error": f"Missing required arguments: {sorted(missing)}"}
        log_tool_result(name, result)
        return result
    try:
        data = spec.handler(client, **arguments)
        result = {"ok": True, "tool": name, "data": data}
        log_tool_result(name, result)
        return result
    except DockaiError as exc:
        result = {"ok": False, "error": str(exc)}
        log_tool_result(name, result)
        return result
    except ValueError as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "hint": (
                "Retry via the tool interface with JSON types: "
                'integers like 25 (not "25"), booleans like false (not "false"). '
                "Do not print tool JSON to the user."
            ),
        }
        log_tool_result(name, result)
        return result
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"Tool execution failed: {exc}"}
        log_tool_result(name, result)
        return result
