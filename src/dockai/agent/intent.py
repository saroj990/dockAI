"""Local-first NL intent: normalize → classify → extract slots → tool or LLM."""

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

# Diagnosis / explanation — always fall through to the LLM.
_NEEDS_LLM = re.compile(
    r"\b("
    r"why|how\s+come|what('?s|\s+is|\s+could|\s+might)|"
    r"issue|problem|wrong|broken|failing|troubleshoot|diagnos|"
    r"explain|analy[sz]e|suggest|should\s+i|help\s+me\s+understand"
    r")\b",
    re.IGNORECASE,
)

# Shared politeness / filler stripped once for all intents.
_LEAD_IN = re.compile(
    r"^(?:(?:can|could|would)\s+(?:we|you|I)\s+|please\s+)+",
    re.IGNORECASE,
)
_SHOW_GIVE_GET = re.compile(
    r"^(?:show|give|get|tell|fetch|pull|display)\s+(?:me\s+)?",
    re.IGNORECASE,
)
_TRAILING_PLEASE = re.compile(r"\s+please\.?$", re.IGNORECASE)

_CONFIDENCE_RUN = 0.8

# --- Per-intent patterns (applied after normalize_intent_text) ---

_FOCUSED_LOGS = re.compile(
    r"^(?:show|get|fetch|pull)?\s*"
    r"(?:its|the)?\s*"
    r"(?:last\s+(\d+)\s+)?"
    r"(?:log\s+lines?|logs?)$",
    re.IGNORECASE,
)

_LOGS_OF_TARGET = re.compile(
    r"^(?:show|get|fetch|pull|tail|dig\s+into)?\s*"
    r"(?:the\s+)?(?:last\s+(\d+)\s+lines?\s+of\s+)?"
    r"(.+?)\s+logs?"
    r"(?:\s+for\s+last\s+(\d+)\s+lines?)?$",
    re.IGNORECASE,
)

_LOGS_FOR_TARGET = re.compile(
    r"^(?:show|get|fetch|pull|tail|dig\s+into)?\s*"
    r"(?:the\s+)?logs?\s+(?:of|for|from)\s+(.+?)"
    r"(?:\s+last\s+(\d+)\s+lines?)?$",
    re.IGNORECASE,
)

_LIFECYCLE = re.compile(
    r"^(start|stop|restart)\s+(?:the\s+)?(?:container\s+)?"
    r"(?:(?:with\s+)?name\s+|named\s+|called\s+)?(.+)$",
    re.IGNORECASE,
)

_INSPECT = re.compile(
    r"^(?:inspect|details|info)\s+"
    r"(?:(?:for|of|on)\s+)?(?:the\s+)?(?:container\s+)?(.+)$",
    re.IGNORECASE,
)

_SEARCH = re.compile(
    r"^(?:find|search(?:\s+for)?|show|list)?\s*"
    r"containers?\s+(?:named|with\s+name|called)\s+([a-z0-9][\w.-]*)$",
    re.IGNORECASE,
)

_UPTIME = re.compile(
    r"^(?:show|list|get|pull)?\s*"
    r"(?:the\s+)?uptime\s+(?:of\s+)?"
    r"(?:(?:all|running|exited|stopped|dead)\s+)?"
    r"(?:my\s+|the\s+)?containers?$"
    r"|^(?:show|list|get|pull)?\s*"
    r"(?:the\s+)?containers?\s+uptime$",
    re.IGNORECASE,
)

_LIST = re.compile(
    r"^(?:show|list|get|pull|display|can\s+you)?\s*"
    r"(?:the\s+)?"
    r"(?:only\s+[\w\s,/]+?\s+of\s+)?"
    r"(?:only\s+)?"
    r"(?:all\s+|running\s+|exited\s+|stopped\s+|dead\s+|inactive\s+|non[-\s]?running\s+)?"
    r"(?:my\s+|the\s+)?containers?"
    r"(?:\s+(?:that|which)\s+(?:are\s+)?not\s+running(?:\s+right\s+now)?)?"
    r"(?:\s+that\s+are\s+(?:running|exited|stopped|dead|inactive))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentMatch:
    """Result of local intent resolution."""

    intent: str
    tool: str | None
    arguments: dict[str, Any]
    confidence: float
    label: str


def normalize_intent_text(user_text: str) -> str:
    """Collapse fluff shared by all intents; keep original for scope helpers."""
    text = normalize_user_text(user_text)
    if not text:
        return ""
    text = _LEAD_IN.sub("", text).strip()
    text = _SHOW_GIVE_GET.sub("", text).strip()
    text = _TRAILING_PLEASE.sub("", text).strip()
    return text


def resolve_intent(
    user_text: str,
    *,
    focus_container: str | None = None,
) -> IntentMatch:
    """
    Classify NL into a Docker tool call when confidence is high.

    Returns intent=unknown / confidence=0 when the LLM should handle the turn.
    """
    original = normalize_user_text(user_text)
    if not original:
        return _unknown()

    if _NEEDS_LLM.search(original):
        return IntentMatch(
            intent="troubleshoot",
            tool=None,
            arguments={},
            confidence=0.0,
            label="intent:troubleshoot",
        )

    core = normalize_intent_text(user_text)
    if not core:
        return _unknown()
    lower = core.lower()

    # Focused follow-up logs (needs session focus).
    if focus_container:
        focused = _FOCUSED_LOGS.fullmatch(lower)
        if focused:
            args: dict[str, Any] = {"target": focus_container}
            if focused.group(1):
                args["tail"] = int(focused.group(1))
            return IntentMatch(
                intent="logs",
                tool="get_container_logs",
                arguments=args,
                confidence=0.95,
                label="intent:logs",
            )

    # Lifecycle before logs so "restart" is not eaten by other cues.
    mut = _LIFECYCLE.fullmatch(lower)
    if mut:
        action, target = mut.group(1).lower(), _clean_target(mut.group(2))
        if target and not _looks_like_question(target):
            return IntentMatch(
                intent=action,
                tool=f"{action}_container",
                arguments={"target": target},
                confidence=0.95,
                label=f"intent:{action}",
            )

    logs = _match_logs(lower)
    if logs is not None:
        return logs

    insp = _INSPECT.fullmatch(lower)
    if insp:
        target = _clean_target(insp.group(1))
        if target and not _looks_like_question(target):
            return IntentMatch(
                intent="inspect",
                tool="inspect_container",
                arguments={"target": target},
                confidence=0.9,
                label="intent:inspect",
            )

    search = _SEARCH.fullmatch(lower)
    if search:
        return IntentMatch(
            intent="search",
            tool="search_containers",
            arguments={"keyword": search.group(1), "running_only": False},
            confidence=0.9,
            label="intent:search",
        )

    if _UPTIME.fullmatch(lower):
        args = apply_list_scope(original, "list_uptime", {"all_containers": False})
        columns = parse_columns_from_text(original)
        args["columns"] = columns if columns else ["name", "uptime"]
        return IntentMatch(
            intent="uptime",
            tool="list_uptime",
            arguments=args,
            confidence=0.9,
            label="intent:uptime",
        )

    list_match = _LIST.fullmatch(lower)
    if list_match or _is_column_list_request(lower) or detect_status_filter(original):
        if not (
            list_match
            or _is_column_list_request(lower)
            or re.search(r"\bcontainers?\b", lower)
        ):
            return _unknown()
        args = apply_list_scope(
            original,
            "list_containers",
            {"all_containers": False},
        )
        columns = parse_columns_from_text(original)
        if columns:
            args["columns"] = columns
        if columns and set(columns) <= {"name", "uptime"} and "uptime" in columns:
            return IntentMatch(
                intent="list",
                tool="list_uptime",
                arguments=apply_list_scope(original, "list_uptime", args),
                confidence=0.9,
                label="intent:list",
            )
        return IntentMatch(
            intent="list",
            tool="list_containers",
            arguments=args,
            confidence=0.9,
            label="intent:list",
        )

    return _unknown()


def _match_logs(lower: str) -> IntentMatch | None:
    match = _LOGS_OF_TARGET.fullmatch(lower)
    if match:
        tail_a, target, tail_b = match.group(1), match.group(2), match.group(3)
        target = _clean_target(target)
        if target and not _looks_like_question(target):
            args: dict[str, Any] = {"target": target}
            tail = tail_a or tail_b
            if tail:
                args["tail"] = int(tail)
            return IntentMatch(
                intent="logs",
                tool="get_container_logs",
                arguments=args,
                confidence=0.95,
                label="intent:logs",
            )

    match = _LOGS_FOR_TARGET.fullmatch(lower)
    if match:
        target = _clean_target(match.group(1))
        if target and not _looks_like_question(target):
            args = {"target": target}
            if match.group(2):
                args["tail"] = int(match.group(2))
            return IntentMatch(
                intent="logs",
                tool="get_container_logs",
                arguments=args,
                confidence=0.95,
                label="intent:logs",
            )
    return None


def _unknown() -> IntentMatch:
    return IntentMatch(
        intent="unknown",
        tool=None,
        arguments={},
        confidence=0.0,
        label="intent:unknown",
    )


def _is_column_list_request(lower: str) -> bool:
    return bool(
        re.search(r"\bonly\b.+\b(name|uptime|status|image|id|restarts)\b", lower)
        and re.search(r"\bcontainers?\b", lower)
    )


def _clean_target(raw: str) -> str:
    text = raw.strip(" .")
    text = re.sub(r"^(container\s+)?(named\s+|called\s+)?", "", text, flags=re.I)
    # Strip trailing fluff: "pg_tileserv containers", "api-server please"
    text = re.sub(r"\s+(containers?|please)$", "", text, flags=re.I)
    return text.strip(" .")


def _looks_like_question(text: str) -> bool:
    return "?" in text or bool(_NEEDS_LLM.search(text))


# Re-export for callers that check diagnosis cues.
NEEDS_LLM_PATTERN = _NEEDS_LLM
CONFIDENCE_RUN = _CONFIDENCE_RUN
