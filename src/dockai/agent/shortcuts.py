"""High-confidence NL shortcuts that skip Ollama for common Docker asks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from dockai.agent.scope import (
    apply_list_scope,
    detect_status_filter,
    normalize_user_text,
)
from dockai.columns import parse_columns_from_text

# If present, the request likely needs real interpretation — do not shortcut.
_NEEDS_LLM = re.compile(
    r"\b("
    r"why|how\s+come|what('?s|\s+is|\s+could|\s+might)|"
    r"issue|problem|wrong|broken|failing|troubleshoot|diagnos|"
    r"explain|analy[sz]e|suggest|should\s+i|help\s+me\s+understand"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Shortcut:
    tool: str
    arguments: dict[str, Any]
    label: str


# Conversational lead-in stripped before log intent matching (LLM not needed).
_LOGS_LEAD_IN = re.compile(
    r"^(?:(?:can|could)\s+(?:we|you|I)\s+|please\s+)+",
    re.IGNORECASE,
)

# "<target> logs" — e.g. "show last 25 lines of api-server logs"
_LOGS_OF_TARGET = re.compile(
    r"^(?:please\s+)?(?:show|get|fetch|pull|tail|dig\s+into)?\s*"
    r"(?:the\s+)?(?:last\s+(\d+)\s+lines?\s+of\s+)?"
    r"(.+?)\s+logs?"
    r"(?:\s+for\s+last\s+(\d+)\s+lines?)?"
    r"(?:\s+please)?$",
    re.IGNORECASE,
)

# "logs for <target>" — e.g. "dig into the logs for saien backend api"
_LOGS_FOR_TARGET = re.compile(
    r"^(?:please\s+)?(?:show|get|fetch|pull|tail|dig\s+into)?\s*"
    r"(?:the\s+)?logs?\s+(?:of|for|from)\s+(.+?)"
    r"(?:\s+last\s+(\d+)\s+lines?)?"
    r"(?:\s+please)?$",
    re.IGNORECASE,
)


def _match_logs_shortcut(lower: str) -> Shortcut | None:
    """Derive get_container_logs from common log phrasing without the LLM."""
    text = _LOGS_LEAD_IN.sub("", lower.strip()).strip()
    if not text:
        return None

    match = _LOGS_OF_TARGET.fullmatch(text)
    if match:
        tail_a, target, tail_b = match.group(1), match.group(2), match.group(3)
        target = _clean_target(target)
        if target and not _looks_like_question(target):
            args: dict[str, Any] = {"target": target}
            tail = tail_a or tail_b
            if tail:
                args["tail"] = int(tail)
            return Shortcut(
                tool="get_container_logs",
                arguments=args,
                label="shortcut:logs",
            )

    match = _LOGS_FOR_TARGET.fullmatch(text)
    if match:
        target = _clean_target(match.group(1))
        if target and not _looks_like_question(target):
            args = {"target": target}
            if match.group(2):
                args["tail"] = int(match.group(2))
            return Shortcut(
                tool="get_container_logs",
                arguments=args,
                label="shortcut:logs",
            )

    return None


def match_shortcut(
    user_text: str,
    *,
    focus_container: str | None = None,
) -> Shortcut | None:
    """
    Return a tool call when the phrase is unambiguous enough to skip the LLM.

    Conservative: prefer falling through to Ollama over a wrong shortcut.
    """
    text = normalize_user_text(user_text)
    if not text or _NEEDS_LLM.search(text):
        return None

    lower = text.lower()

    # Focused follow-up logs: "show its last 25 log lines" / "show its logs"
    if focus_container:
        focused_logs = re.fullmatch(
            r"(?:please\s+)?(?:show|get|fetch|pull)?\s*"
            r"(?:me\s+)?(?:its|the)?\s*"
            r"(?:last\s+(\d+)\s+)?"
            r"(?:log\s+lines?|logs?)",
            lower,
        )
        if focused_logs:
            args: dict[str, Any] = {"target": focus_container}
            if focused_logs.group(1):
                args["tail"] = int(focused_logs.group(1))
            return Shortcut(
                tool="get_container_logs",
                arguments=args,
                label="shortcut:logs",
            )

    # Mutations: "stop api-server" / "can you restart container with name my-app"
    mut = re.fullmatch(
        r"(?:(?:can\s+you|could\s+you|please)\s+)?"
        r"(start|stop|restart)\s+(?:the\s+)?(?:container\s+)?"
        r"(?:(?:with\s+)?name\s+|named\s+|called\s+)?(.+)",
        lower,
    )
    if mut:
        action, target = mut.group(1), mut.group(2).strip(" .")
        if target and not _looks_like_question(target):
            return Shortcut(
                tool=f"{action}_container",
                arguments={"target": target},
                label=f"shortcut:{action}",
            )

    logs_shortcut = _match_logs_shortcut(lower)
    if logs_shortcut is not None:
        return logs_shortcut

    # Inspect: "inspect api-server"
    insp = re.fullmatch(
        r"(?:please\s+)?inspect\s+(?:container\s+)?(.+)",
        lower,
    )
    if insp:
        target = _clean_target(insp.group(1))
        if target:
            return Shortcut(
                tool="inspect_container",
                arguments={"target": target},
                label="shortcut:inspect",
            )

    # Search: "find containers named flink" / "containers named flink"
    search = re.fullmatch(
        r"(?:please\s+)?(?:find|search(?:\s+for)?|show|list)?\s*"
        r"containers?\s+(?:named|with\s+name|called)\s+([a-z0-9][\w.-]*)",
        lower,
    )
    if search:
        return Shortcut(
            tool="search_containers",
            arguments={"keyword": search.group(1), "running_only": False},
            label="shortcut:search",
        )

    # Uptime-focused list (optional status word between "of" and "containers")
    if re.fullmatch(
        r"(?:please\s+)?(?:show|list|get|pull)?\s*"
        r"(?:me\s+)?(?:the\s+)?uptime\s+(?:of\s+)?"
        r"(?:(?:all|running|exited|stopped|dead)\s+)?"
        r"(?:my\s+|the\s+)?containers?",
        lower,
    ) or re.fullmatch(
        r"(?:please\s+)?(?:show|list|get|pull)?\s*"
        r"(?:me\s+)?(?:the\s+)?containers?\s+uptime",
        lower,
    ):
        args = apply_list_scope(text, "list_uptime", {"all_containers": False})
        columns = parse_columns_from_text(text)
        if columns:
            args["columns"] = columns
        else:
            args["columns"] = ["name", "uptime"]
        return Shortcut(tool="list_uptime", arguments=args, label="shortcut:uptime")

    # List containers (running / all / exited / stopped) — including column subsets
    # Also: "show me only running containers" / "show me exited containers"
    list_match = re.fullmatch(
        r"(?:please\s+)?(?:can\s+you\s+)?(?:show|list|get|pull|display)?\s*"
        r"(?:me\s+)?(?:the\s+)?"
        r"(?:only\s+[\w\s,/]+?\s+of\s+)?"  # "only name and uptime of"
        r"(?:only\s+)?"  # "only running containers"
        r"(?:all\s+|running\s+|exited\s+|stopped\s+|dead\s+)?"
        r"(?:my\s+|the\s+)?containers?"
        r"(?:\s+that\s+are\s+(?:running|exited|stopped|dead))?"
        r"(?:\s+please)?",
        lower,
    )
    if list_match or _is_column_list_request(lower) or detect_status_filter(text):
        # Only treat as a list ask when containers are mentioned (or column list).
        if not (
            list_match
            or _is_column_list_request(lower)
            or re.search(r"\bcontainers?\b", lower)
        ):
            return None
        args = apply_list_scope(
            text,
            "list_containers",
            {"all_containers": False},
        )
        columns = parse_columns_from_text(text)
        if columns:
            args["columns"] = columns
        # Prefer list_uptime when uptime is the only extra focus beyond name
        if columns and set(columns) <= {"name", "uptime"} and "uptime" in columns:
            return Shortcut(
                tool="list_uptime",
                arguments=apply_list_scope(text, "list_uptime", args),
                label="shortcut:list",
            )
        return Shortcut(
            tool="list_containers",
            arguments=args,
            label="shortcut:list",
        )

    return None


def needs_docker_tool(
    user_text: str,
    *,
    focus_container: str | None = None,
) -> bool:
    """
    True when this user turn should call a Docker tool (not answer from chat memory).

    Conservative: troubleshooting / explain asks return False.
    """
    if match_shortcut(user_text, focus_container=focus_container) is not None:
        return True
    text = normalize_user_text(user_text)
    if not text or _NEEDS_LLM.search(text):
        return False
    lower = text.lower()
    if re.search(
        r"\b(?:can\s+you|could\s+you|please)\s+"
        r"(?:restart|start|stop|inspect)\b",
        lower,
    ):
        return True
    if re.search(r"\blogs?\b", lower) and re.search(
        r"\b(?:for|of|from|last|lines?|show|get|fetch|pull|dig)\b",
        lower,
    ):
        return True
    if re.search(r"\b(?:inspect|uptime)\b", lower) and re.search(
        r"\bcontainer",
        lower,
    ):
        return True
    return bool(re.search(r"\b(?:list|show|pull|get)\b.+\bcontainers?\b", lower))


def _is_column_list_request(lower: str) -> bool:
    """Catch 'only name and uptime of running containers' style asks."""
    return bool(
        re.search(r"\bonly\b.+\b(name|uptime|status|image|id|restarts)\b", lower)
        and re.search(r"\bcontainers?\b", lower)
    )


def _clean_target(raw: str) -> str:
    text = raw.strip(" .")
    text = re.sub(r"^(container\s+)?(named\s+|called\s+)?", "", text)
    text = re.sub(r"\s+(container|please)$", "", text)
    return text.strip(" .")


def _looks_like_question(text: str) -> bool:
    return "?" in text or bool(_NEEDS_LLM.search(text))
