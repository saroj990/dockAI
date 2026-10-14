"""Server-side list scope: running-only and status filters from user intent."""

from __future__ import annotations

import re
from typing import Any

# Explicit "show everything" (no status filter).
_WANTS_ALL_EXPLICIT = re.compile(
    r"\b("
    r"all\s+containers?|"
    r"including\s+(stopped|exited|dead)|"
    r"not\s+just\s+running|running\s+and\s+stopped"
    r")\b",
    re.IGNORECASE,
)

# Status-scoped asks. "stopped" → exited/dead (Docker has no "stopped" status).
_STATUS_RUNNING = re.compile(
    r"\b("
    r"running(\s+containers?)?|"
    r"containers?\s+that\s+are\s+running|"
    r"only\s+running"
    r")\b",
    re.IGNORECASE,
)
_STATUS_EXITED = re.compile(
    r"\b("
    r"exited\s+containers?|"
    r"containers?\s+that\s+(have\s+)?exited|"
    r"containers?\s+with\s+status\s+exited"
    r")\b",
    re.IGNORECASE,
)
_STATUS_STOPPED = re.compile(
    r"\b("
    r"stopped\s+containers?|"
    r"containers?\s+that\s+are\s+stopped|"
    r"containers?\s+with\s+status\s+stopped"
    r")\b",
    re.IGNORECASE,
)
_STATUS_DEAD = re.compile(
    r"\b("
    r"dead\s+containers?|"
    r"containers?\s+that\s+are\s+dead|"
    r"containers?\s+with\s+status\s+dead"
    r")\b",
    re.IGNORECASE,
)

_LIST_SCOPE_TOOLS = frozenset({"list_containers", "list_uptime", "search_containers"})


def detect_status_filter(user_text: str) -> str | None:
    """
    Return a status filter key when the user asks for a specific state.

    None means no status filter (running-default or explicit all).
    """
    text = user_text or ""
    # "all containers" / "including exited" → no status filter
    if _WANTS_ALL_EXPLICIT.search(text) and not re.search(
        r"\ball\s+running\b", text, re.IGNORECASE
    ):
        return None
    if _STATUS_DEAD.search(text):
        return "dead"
    if _STATUS_EXITED.search(text):
        return "exited"
    if _STATUS_STOPPED.search(text):
        return "stopped"
    if _STATUS_RUNNING.search(text) or re.search(
        r"\ball\s+running\b", text, re.IGNORECASE
    ):
        return "running"
    return None


def wants_all_containers(user_text: str) -> bool:
    """True when Docker must be queried with all=True (full list or non-running status)."""
    text = user_text or ""
    if re.search(r"\ball\s+running\b", text, re.IGNORECASE):
        return False
    status = detect_status_filter(text)
    if status in {"exited", "stopped", "dead"}:
        return True
    return bool(_WANTS_ALL_EXPLICIT.search(text))


def wants_running_only(user_text: str) -> bool:
    """True when the user asks for running containers only."""
    return detect_status_filter(user_text) == "running"


def apply_list_scope(
    user_text: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Enforce list scope from user text before a tool runs.

    - running → all_containers=false
    - exited/stopped/dead → all_containers=true + status filter
    - explicit all → all_containers=true, clear status filter
    """
    args = dict(arguments or {})
    if tool_name not in _LIST_SCOPE_TOOLS:
        return args

    status = detect_status_filter(user_text)
    explicit_all = bool(_WANTS_ALL_EXPLICIT.search(user_text or "")) and (
        status is None
        and not re.search(r"\ball\s+running\b", user_text or "", re.IGNORECASE)
    )

    if status == "running":
        if tool_name in {"list_containers", "list_uptime"}:
            args["all_containers"] = False
            args.pop("status", None)
        elif tool_name == "search_containers":
            args["running_only"] = True
            args.pop("status", None)
        return args

    if status in {"exited", "stopped", "dead"}:
        if tool_name in {"list_containers", "list_uptime"}:
            args["all_containers"] = True
            args["status"] = status
        elif tool_name == "search_containers":
            args["running_only"] = False
            args["status"] = status
        return args

    if explicit_all and tool_name in {"list_containers", "list_uptime"}:
        args["all_containers"] = True
        args.pop("status", None)

    return args
