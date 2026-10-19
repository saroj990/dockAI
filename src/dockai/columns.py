"""Map natural-language / tool column requests to Rich table keys."""

from __future__ import annotations

import re
from typing import Any

SUPPORTED_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "status",
    "image",
    "uptime",
    "restarts",
)

_ALIASES: dict[str, str] = {
    "id": "id",
    "ids": "id",
    "container id": "id",
    "container_id": "id",
    "name": "name",
    "names": "name",
    "container name": "name",
    "container_name": "name",
    "status": "status",
    "state": "status",
    "image": "image",
    "images": "image",
    "uptime": "uptime",
    "up time": "uptime",
    "up-time": "uptime",
    "restarts": "restarts",
    "restart": "restarts",
    "restart count": "restarts",
    "restart_count": "restarts",
}

# Phrases that suggest the user wants a column subset, not the default table.
_SUBSET_HINT = re.compile(
    r"\b(only|just|solely|columns?|fields?|show\s+me\s+the)\b",
    re.IGNORECASE,
)

# Explicit NL column lists (validated for unknown tokens).
_EXPLICIT_COLUMN_PHRASES = (
    re.compile(r"\bonly\s+(.+?)\s+of\b", re.IGNORECASE),
    re.compile(r"\bonly\s+(.+?)\s+for\b", re.IGNORECASE),
    re.compile(
        r"\b(?:show|display|pull|list)\s+(.+?)\s+in\s+a\s+table\b",
        re.IGNORECASE,
    ),
)


def supported_columns_message() -> str:
    return ", ".join(SUPPORTED_COLUMNS)


def unknown_columns_message(tokens: list[str]) -> str:
    listed = ", ".join(sorted({t.strip() for t in tokens if t.strip()}))
    return (
        f"Unknown column name(s): {listed}. "
        f"Supported columns: {supported_columns_message()}."
    )


def normalize_column_token(token: str) -> str | None:
    key = " ".join(token.strip().lower().replace("-", " ").replace("_", " ").split())
    return _ALIASES.get(key)


def _split_column_phrase(phrase: str) -> list[str]:
    normalized = re.sub(r"\s+and\s+", ",", phrase.strip(), flags=re.IGNORECASE)
    return [part.strip() for part in normalized.split(",") if part.strip()]


def coerce_columns_arg(value: Any, *, strict: bool = False) -> list[str] | None:
    """Accept list/tuple or comma-separated string from the LLM."""
    if value is None:
        return None
    raw: list[str]
    if isinstance(value, str):
        raw = [part for part in re.split(r"[,|/]+", value) if part.strip()]
    elif isinstance(value, (list, tuple)):
        raw = [str(item) for item in value]
    else:
        return None
    columns: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = normalize_column_token(item)
        if normalized:
            if normalized not in seen:
                seen.add(normalized)
                columns.append(normalized)
        else:
            token = item.strip()
            if token:
                unknown.append(token)
    if strict and unknown:
        raise ValueError(unknown_columns_message(unknown))
    if not columns:
        return None
    return columns


def unknown_columns_in_user_text(user_text: str) -> list[str]:
    """Return unsupported column tokens from explicit NL column lists."""
    text = (user_text or "").strip()
    if not text:
        return []
    unknown: list[str] = []
    for pattern in _EXPLICIT_COLUMN_PHRASES:
        match = pattern.search(text)
        if not match:
            continue
        for token in _split_column_phrase(match.group(1)):
            if not normalize_column_token(token):
                unknown.append(token)
    return unknown


def validate_user_column_request(user_text: str) -> None:
    """Raise ValueError when the user names unsupported columns explicitly."""
    bad = unknown_columns_in_user_text(user_text)
    if bad:
        raise ValueError(unknown_columns_message(bad))


def parse_columns_from_text(user_text: str) -> list[str] | None:
    """
    Detect requested columns from the user message.

    Returns None when the user did not ask for a specific subset (use tool defaults).
    """
    text = (user_text or "").strip()
    if not text:
        return None

    # Prefer explicit enumerations: "name and uptime", "id, status, and name"
    # Longer aliases first so "restart count" wins over "restart".
    lowered = text.lower()
    matches: list[tuple[int, str]] = []
    occupied: list[tuple[int, int]] = []
    for alias in sorted(_ALIASES.keys(), key=len, reverse=True):
        pattern = re.compile(r"\b" + re.escape(alias) + r"\b")
        for hit in pattern.finditer(lowered):
            start, end = hit.span()
            if any(start < o_end and end > o_start for o_start, o_end in occupied):
                continue
            occupied.append((start, end))
            matches.append((start, _ALIASES[alias]))

    found: list[str] = []
    seen: set[str] = set()
    for _, col in sorted(matches, key=lambda item: item[0]):
        if col not in seen:
            seen.add(col)
            found.append(col)

    if not found:
        return None

    # Single bare "name" in a general sentence is too weak; require subset hint
    # or at least two columns (e.g. name and uptime).
    if len(found) == 1 and not _SUBSET_HINT.search(text):
        return None

    return found


def resolve_columns(
    *,
    user_text: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
    default: list[str] | None = None,
) -> list[str]:
    """
    Resolve display columns.

    Priority: validated tool args > parsed user text > default.
    """
    fallback = list(default or ["id", "name", "status", "image", "uptime"])
    args = tool_arguments or {}
    from_args = coerce_columns_arg(args.get("columns"))
    if from_args:
        return from_args
    from_text = parse_columns_from_text(user_text or "")
    if from_text:
        return from_text
    return fallback
