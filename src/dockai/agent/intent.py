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
from dockai.agent.target_match import refine_target_with_focus
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

# Shared politeness / filler stripped for all intents (applied repeatedly).
_LEAD_IN = re.compile(
    r"^(?:"
    r"(?:can|could|would)\s+(?:we|you|I)\s+"
    r"|please\s+"
    r"|let'?s\s+"
    r"|let\s+me\s+"
    r"|i\s+(?:want|need)\s+to\s+"
    r"|i'?d\s+like\s+to\s+"
    r")+",
    re.IGNORECASE,
)
# Soft action verbs before the real ask ("see logs", "have the logs", "show me …").
_SOFT_VERB = re.compile(
    r"^(?:"
    r"show|give|get|tell|fetch|pull|display|see|have|view|check|read|open|tail|"
    r"dig\s+into"
    r")\s+(?:me\s+|us\s+)?",
    re.IGNORECASE,
)
_TRAILING_PLEASE = re.compile(r"\s+please\.?$", re.IGNORECASE)
# Extra wrappers common on diagnosis / status asks (applied before pattern match).
_DIAGNOSE_LEAD_IN = re.compile(
    r"^(?:"
    r"(?:hey|hi|hello|so|well|ok(?:ay)?)[,\s]+|"
    r"(?:quick\s+question|real\s+quick)[,\s:]+|"
    r"(?:i'?m\s+|i\s+am\s+)?wondering\s+(?:if|whether)\s+|"
    r"(?:do\s+you\s+know|can\s+you\s+tell\s+me|let\s+me\s+know)\s+(?:if|whether)\s+|"
    r"(?:can\s+you\s+(?:please\s+)?)?(?:check|verify|confirm)\s+(?:if|whether)\s+|"
    r"help\s+me\s+(?:figure\s+out|understand|see)\s+(?:if|whether\s+)?|"
    r"(?:tell\s+me|find\s+out)\s+(?:if|whether)\s+"
    r")+",
    re.IGNORECASE,
)
# Safe whole-word removal (repeat until stable); avoids container name tokens.
_INTENT_FILLER_WORD = re.compile(
    r"\b("
    r"please|thanks|thank\s+you|"
    r"just|actually|really|literally|maybe|probably|"
    r"currently|still|right\s+now|already|again|today|"
    r"constantly|always|"
    r"hey|so|well|ok(?:ay)?|"
    r"quickly"
    r")\b",
    re.IGNORECASE,
)
# "container/service" wrapper around a name (diagnose targets only).
_CONTAINER_WRAPPER = re.compile(
    r"\b(?:docker\s+)?(?:container|service|pod)s?\b",
    re.IGNORECASE,
)

_CONFIDENCE_RUN = 0.8

# --- Per-intent patterns (applied after normalize_intent_text) ---

_FOCUSED_LOGS = re.compile(
    r"^(?:its|the)?\s*"
    r"(?:last\s+(\d+)\s+)?"
    r"(?:log\s+lines?|logs?)$",
    re.IGNORECASE,
)

# Structural logs shapes (verbs already stripped in normalize):
#   "logs for pg_tileserv" / "the logs of api-server last 25 lines"
#   "last 25 lines of api-server logs" / "pg tileserv logs"
_LOGS_FOR_TARGET = re.compile(
    r"^(?:the\s+)?logs?\s+(?:of|for|from)\s+(.+?)"
    r"(?:\s+last\s+(\d+)\s+lines?)?$",
    re.IGNORECASE,
)
_LOGS_OF_TARGET = re.compile(
    r"^(?:last\s+(\d+)\s+lines?\s+of\s+)?"
    r"(.+?)\s+logs?"
    r"(?:\s+for\s+last\s+(\d+)\s+lines?)?$",
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

# Matched on normalize_diagnose_text output (canonical short form).
_DIAG_RESTART_NAMED = re.compile(
    r"^(?:(?:why|how\s+come)\s+(?:is|are|does|do)|is|are)\s+"
    r"(?:(?:my|the|our|this|that)\s+)?"
    r"(.+?)\s+"
    r"(?:(?:keep(?:s|ing)?|constantly|always)\s+)?"
    r"(?:restart(?:ing|s|ed)?|crash(?:ing|es|ed)?)$",
    re.IGNORECASE,
)
_DIAG_RESTART_IT = re.compile(
    r"^(?:(?:why|how\s+come)\s+(?:is|are|does|do)|is|are)\s+"
    r"(?:it|this)\s+"
    r"(?:(?:keep(?:s|ing)?|constantly|always)\s+)?"
    r"(?:restart(?:ing|s|ed)?|crash(?:ing|es|ed)?)$",
    re.IGNORECASE,
)
# After fluff strip: "my pg tileserv is restarting" → "is pg tileserv restarting"
_SUBJECT_IS_RESTART = re.compile(
    r"^(?:(?:my|the|our|this|that)\s+)?(.+?)\s+(?:is|are)\s+"
    r"(?:(?:keep(?:s|ing)?|constantly|always)\s+)?"
    r"(restart(?:ing|s|ed)?|crash(?:ing|es|ed)?)$",
    re.IGNORECASE,
)
_SUBJECT_KEEPS_RESTART = re.compile(
    r"^(?:(?:my|the|our|this|that)\s+)?(.+?)\s+keep(?:s|ing)\s+"
    r"(restart(?:ing|s|ed)?|crash(?:ing|es|ed)?)$",
    re.IGNORECASE,
)
_DIAG_ISSUES_NAMED = re.compile(
    r"^(?:(?:why|how\s+come)\s+)?(?:(?:is|are)\s+)?"
    r"(?:(?:my|the|our|this|that)\s+)?(.+?)\s+"
    r"(?:showing|having|getting|seeing|see|with)\s+"
    r"(?:some\s+)?(?:issue|issues|problem|problems|error|errors|trouble)$",
    re.IGNORECASE,
)
_DIAG_ISSUES_IT = re.compile(
    r"^(?:(?:why|how\s+come)\s+)?(?:(?:is|are)\s+)?(?:it|this)\s+"
    r"(?:showing|having|getting|seeing|see|with)\s+"
    r"(?:some\s+)?(?:issue|issues|problem|problems|error|errors|trouble)$",
    re.IGNORECASE,
)
_SUBJECT_HAS_ISSUES = re.compile(
    r"^(?:(?:my|the|our|this|that)\s+)?(.+?)\s+(?:is|are)\s+"
    r"(?:showing|having|getting|seeing)\s+(?:some\s+)?"
    r"(?:issue|issues|problem|problems|error|errors|trouble)$",
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


def _strip_intent_fluff(text: str, *, include_diagnose_leads: bool) -> str:
    """Remove politeness, hedges, and wrappers; collapse whitespace."""
    if not text:
        return ""
    text = text.rstrip("?.!").strip()
    for _ in range(8):
        prev = text
        text = _LEAD_IN.sub("", text).strip()
        if include_diagnose_leads:
            text = _DIAGNOSE_LEAD_IN.sub("", text).strip()
        text = _SOFT_VERB.sub("", text).strip()
        nxt2 = re.sub(r"^the\s+", "", text, count=1, flags=re.IGNORECASE).strip()
        if nxt2 != text and re.match(
            r"^(logs?|containers?|uptime|inspect|details|info|start|stop|restart|"
            r"why|is|are|how)\b",
            nxt2,
            re.IGNORECASE,
        ):
            text = nxt2
        if text == prev:
            break
    for _ in range(4):
        prev = text
        text = _INTENT_FILLER_WORD.sub(" ", text)
        text = " ".join(text.split())
        if text == prev:
            break
    text = _TRAILING_PLEASE.sub("", text).strip()
    return text


def normalize_diagnose_text(user_text: str) -> str:
    """Canonical form for restart/crash diagnosis intent matching."""
    base = normalize_user_text(user_text)
    text = _strip_intent_fluff(base, include_diagnose_leads=True)
    text = _CONTAINER_WRAPPER.sub(" ", text)
    text = " ".join(text.split())
    flipped = _SUBJECT_IS_RESTART.fullmatch(text)
    if flipped:
        target = _clean_target(flipped.group(1))
        verb = flipped.group(2).lower()
        text = f"is {target} {verb}"
    else:
        keeps = _SUBJECT_KEEPS_RESTART.fullmatch(text)
        if keeps:
            target = _clean_target(keeps.group(1))
            verb = keeps.group(2).lower()
            text = f"is {target} {verb}"
    issues = _SUBJECT_HAS_ISSUES.fullmatch(text)
    if issues:
        target = _clean_target(issues.group(1))
        text = f"why {target} showing issues"
    return text.strip()


def normalize_intent_text(user_text: str) -> str:
    """Collapse fluff shared by all intents; keep original for scope helpers."""
    text = normalize_user_text(user_text)
    if not text:
        return ""
    return _strip_intent_fluff(text, include_diagnose_leads=False)


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

    diagnose = _try_diagnose_restart_intent(
        user_text, focus_container=focus_container
    )
    if diagnose is not None:
        return diagnose

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
            target = refine_target_with_focus(target, focus_container)
            return IntentMatch(
                intent=action,
                tool=f"{action}_container",
                arguments={"target": target},
                confidence=0.95,
                label=f"intent:{action}",
            )

    logs = _match_logs(lower, focus_container=focus_container)
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


def _match_logs(
    lower: str,
    *,
    focus_container: str | None = None,
) -> IntentMatch | None:
    # Prefer "logs for <target>" so "logs for pg tileserv" is not parsed as
    # target="logs for pg" via the "<target> logs" shape.
    match = _LOGS_FOR_TARGET.fullmatch(lower)
    if match:
        target = _clean_target(match.group(1))
        target = refine_target_with_focus(target, focus_container)
        if target and not _looks_like_question(target) and not _bad_log_target(target):
            args: dict[str, Any] = {"target": target}
            if match.group(2):
                args["tail"] = int(match.group(2))
            return IntentMatch(
                intent="logs",
                tool="get_container_logs",
                arguments=args,
                confidence=0.95,
                label="intent:logs",
            )

    match = _LOGS_OF_TARGET.fullmatch(lower)
    if match:
        tail_a, target, tail_b = match.group(1), match.group(2), match.group(3)
        target = refine_target_with_focus(
            _clean_target(target), focus_container
        )
        if target and not _looks_like_question(target) and not _bad_log_target(target):
            args = {"target": target}
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
    return None


def _validate_diagnose_target(raw: str) -> str | None:
    target = _clean_target(raw)
    if not target or _bad_log_target(target) or _looks_like_question(target):
        return None
    if re.match(r"^(?:containers?|services?|pods?)$", target, re.IGNORECASE):
        return None
    return target


def extract_diagnose_container_target(
    text: str,
    *,
    focus_container: str | None = None,
) -> str | None:
    """Container name from restart/crash or issues phrasing (after normalization)."""
    canonical = normalize_diagnose_text(text)
    if not canonical:
        return None
    if focus_container and (
        _DIAG_RESTART_IT.fullmatch(canonical)
        or _DIAG_ISSUES_IT.fullmatch(canonical)
    ):
        return focus_container

    for pattern in (_DIAG_RESTART_NAMED, _DIAG_ISSUES_NAMED):
        match = pattern.fullmatch(canonical)
        if not match:
            continue
        target = _validate_diagnose_target(match.group(1))
        if target is None:
            continue
        return refine_target_with_focus(target, focus_container)
    return None


def extract_named_restart_target(
    text: str,
    *,
    focus_container: str | None = None,
) -> str | None:
    """Backward-compatible alias for diagnose container extraction."""
    return extract_diagnose_container_target(
        text, focus_container=focus_container
    )


def is_placeholder_tool_target(target: str) -> bool:
    """True when the model passed a schema placeholder instead of a real name."""
    text = (target or "").strip()
    if not text:
        return True
    if "<" in text or ">" in text:
        return True
    lower = text.lower()
    if "container-name" in lower or lower in {
        "container",
        "name",
        "target",
        "container_name",
        "container-name-or-id",
    }:
        return True
    return False


def reconcile_troubleshoot_target(
    user_text: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    focus_container: str | None = None,
) -> dict[str, Any]:
    """Replace placeholder troubleshoot targets with names from the user message."""
    args = dict(arguments or {})
    if tool_name != "troubleshoot_container_logs":
        return args
    target = str(args.get("target") or "").strip()
    if not is_placeholder_tool_target(target):
        return args
    extracted = extract_diagnose_container_target(
        user_text,
        focus_container=focus_container,
    )
    if extracted:
        args["target"] = refine_target_with_focus(extracted, focus_container)
    elif focus_container and is_placeholder_tool_target(target):
        args["target"] = focus_container
    return args


def _try_diagnose_restart_intent(
    user_text: str,
    *,
    focus_container: str | None,
) -> IntentMatch | None:
    """Named restart/crash asks → troubleshoot_container_logs (skip LLM routing)."""
    target = extract_diagnose_container_target(
        user_text, focus_container=focus_container
    )
    if target is None:
        return None
    return IntentMatch(
        intent="diagnose",
        tool="troubleshoot_container_logs",
        arguments={"target": target},
        confidence=0.9,
        label="intent:diagnose",
    )


def _bad_log_target(target: str) -> bool:
    """Reject targets that are clearly not container names."""
    t = target.strip().lower()
    if not t or t in {"the", "a", "an", "my", "its", "all"}:
        return True
    if t.startswith("logs ") or t == "logs":
        return True
    return False


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
    text = re.sub(
        r"^(?:(?:the|my|our|this|that)\s+)+",
        "",
        text,
        flags=re.I,
    )
    text = _CONTAINER_WRAPPER.sub(" ", text)
    text = re.sub(
        r"\s+(?:right\s+now|anymore|again|today|currently|still|please)$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+(containers?|please)$", "", text, flags=re.I)
    return " ".join(text.split()).strip(" .")


def _looks_like_question(text: str) -> bool:
    return "?" in text or bool(_NEEDS_LLM.search(text))


# Re-export for callers that check diagnosis cues.
NEEDS_LLM_PATTERN = _NEEDS_LLM
CONFIDENCE_RUN = _CONFIDENCE_RUN
