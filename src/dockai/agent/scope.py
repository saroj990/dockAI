"""Server-side list scope: running-only and status filters from user intent."""

from __future__ import annotations

import re
from typing import Any

# Common typos: runnning, runing → running (before status detection).
_RUNNING_TYPO = re.compile(r"\brun+ing\b", re.IGNORECASE)


def normalize_user_text(user_text: str) -> str:
    """Collapse whitespace and fix high-confidence status typos."""
    text = " ".join((user_text or "").strip().split())
    return _RUNNING_TYPO.sub("running", text)


# Explicit "show everything" (no status filter).
_WANTS_ALL_EXPLICIT = re.compile(
    r"\b("
    r"all\s+containers?|"
    r"including\s+(stopped|exited|dead)|"
    r"not\s+just\s+running|running\s+and\s+stopped"
    r")\b",
    re.IGNORECASE,
)

# Non-running / inactive (must be checked before generic "running" patterns).
_STATUS_NOT_RUNNING = re.compile(
    r"\b("
    r"inactive(\s+containers?)?|"
    r"(?:containers?\s+)?(?:that\s+|which\s+)?(?:are\s+)?not\s+running|"
    r"not\s+running(?:\s+right\s+now)?|"
    r"non[-\s]?running(\s+containers?)?|"
    r"(?:all\s+)?containers?\s+except\s+running|"
    r"except\s+running(?:\s+ones?)?"
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

# Model sometimes calls search_containers with a status word as keyword.
_SEARCH_KEYWORD_AS_STATUS: dict[str, str] = {
    "inactive": "not_running",
    "stopped": "stopped",
    "exited": "exited",
    "dead": "dead",
    "running": "running",
    "notrunning": "not_running",
    "nonrunning": "not_running",
}

_BARE_STATUS_FOLLOWUP = re.compile(
    r"^(?:show(?:\s+me)?\s+)?(?:the\s+)?"
    r"(inactive|not\s+running|non[-\s]?running|stopped|exited|dead|running)"
    r"(?:\s+(?:ones|containers?))?(?:\s+please)?\.?$",
    re.IGNORECASE,
)


def is_bare_status_followup(user_text: str) -> bool:
    return bool(_BARE_STATUS_FOLLOWUP.match(normalize_user_text(user_text)))


def effective_list_user_text(user_text: str, list_context: str | None) -> str:
    """Merge prior list ask when the user sends a short status-only follow-up."""
    text = normalize_user_text(user_text)
    if list_context and is_bare_status_followup(text):
        return normalize_user_text(f"{list_context}. {text}")
    return text


def _mentions_running_intent(text: str) -> bool:
    if _STATUS_NOT_RUNNING.search(text):
        return False
    if re.search(r"\b(?:not|non[-\s]?)\s*running\b", text, re.IGNORECASE):
        return False
    if re.search(r"\bexcept\s+running\b", text, re.IGNORECASE):
        return False
    return bool(_STATUS_RUNNING.search(text)) or bool(
        re.search(r"\ball\s+running\b", text, re.IGNORECASE)
    )


def detect_status_filter(user_text: str) -> str | None:
    """
    Return a status filter key when the user asks for a specific state.

    None means no status filter (running-default or explicit all).
    """
    text = normalize_user_text(user_text)
    if _WANTS_ALL_EXPLICIT.search(text) and not re.search(
        r"\ball\s+running\b", text, re.IGNORECASE
    ):
        if _STATUS_NOT_RUNNING.search(text) or re.search(
            r"\bexcept\s+running\b", text, re.IGNORECASE
        ):
            return "not_running"
        return None
    if _STATUS_NOT_RUNNING.search(text) or re.search(
        r"\bexcept\s+running\b", text, re.IGNORECASE
    ):
        return "not_running"
    if _STATUS_DEAD.search(text):
        return "dead"
    if _STATUS_EXITED.search(text):
        return "exited"
    if _STATUS_STOPPED.search(text):
        return "stopped"
    if _mentions_running_intent(text):
        return "running"
    return None


def wants_all_containers(user_text: str) -> bool:
    """True when Docker must be queried with all=True (full list or non-running status)."""
    text = normalize_user_text(user_text)
    if re.search(r"\ball\s+running\b", text, re.IGNORECASE):
        return False
    status = detect_status_filter(text)
    if status in {"exited", "stopped", "dead", "not_running"}:
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
    - exited/stopped/dead/not_running → all_containers=true + status filter
    - explicit all → all_containers=true, clear status filter
    """
    args = dict(arguments or {})
    if tool_name not in _LIST_SCOPE_TOOLS:
        return args

    text = normalize_user_text(user_text)
    status = detect_status_filter(text)
    explicit_all = bool(_WANTS_ALL_EXPLICIT.search(text)) and (
        status is None
        and not re.search(r"\ball\s+running\b", text, re.IGNORECASE)
    )

    if status == "running":
        if tool_name in {"list_containers", "list_uptime"}:
            args["all_containers"] = False
            args.pop("status", None)
        elif tool_name == "search_containers":
            args["running_only"] = True
            args.pop("status", None)
        return args

    if status in {"exited", "stopped", "dead", "not_running"}:
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


def reconcile_tool_for_list_intent(
    user_text: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    list_context: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Redirect mistaken name-search tools to list_containers when the user asked
    for a container state filter.
    """
    effective = effective_list_user_text(user_text, list_context)
    args = apply_list_scope(effective, tool_name, arguments)

    if tool_name != "search_containers":
        return tool_name, args

    keyword = (args.get("keyword") or "").strip().lower()
    normalized_kw = re.sub(r"[\s_-]+", "", keyword)
    status_from_text = detect_status_filter(effective)
    status_from_kw = _SEARCH_KEYWORD_AS_STATUS.get(keyword) or _SEARCH_KEYWORD_AS_STATUS.get(
        normalized_kw
    )
    if status_from_text or status_from_kw:
        list_args = apply_list_scope(
            effective,
            "list_containers",
            {
                "all_containers": wants_all_containers(effective),
                "status": status_from_text or status_from_kw,
            },
        )
        if list_args.get("status") is None and (status_from_text or status_from_kw):
            list_args["status"] = status_from_text or status_from_kw
            list_args["all_containers"] = True
        return "list_containers", list_args

    return tool_name, args
