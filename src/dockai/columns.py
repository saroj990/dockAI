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


def normalize_column_token(token: str) -> str | None:
    key = " ".join(token.strip().lower().replace("-", " ").replace("_", " ").split())
    return _ALIASES.get(key)


def coerce_columns_arg(value: Any) -> list[str] | None:
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
    seen: set[str] = set()
    for item in raw:
        normalized = normalize_column_token(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            columns.append(normalized)
    return columns or None


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
