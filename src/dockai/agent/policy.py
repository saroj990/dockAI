"""Clear refusals for out-of-scope / restricted actions."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Restriction:
    """A matched restricted request with a user-facing refusal."""

    kind: str
    message: str


_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "delete_container",
        re.compile(
            r"\b(delete|remove|rm|destroy)\b[\w\s-]*\bcontainers?\b"
            r"|\bcontainers?\b[\w\s-]*\b(delete|remove|rm|destroy)\b"
            r"|\bdocker\s+rm\b"
            r"|\b(delete|remove)\s+a\s+container\b",
            re.IGNORECASE,
        ),
        (
            "Not supported: deleting or removing containers is restricted in dockai.\n"
            "Allowed state changes: start, stop, and restart — only after you confirm.\n"
            "I will not stop a container as a substitute for delete/remove.\n"
            "If you meant stop (not delete), say clearly: stop <container-name>."
        ),
    ),
    (
        "prune",
        re.compile(
            r"\b(prune|docker\s+system\s+prune|clean\s+up\s+unused)\b",
            re.IGNORECASE,
        ),
        (
            "Not supported: prune / cleanup of unused Docker resources is restricted.\n"
            "dockai will not run prune, volume delete, or image delete commands."
        ),
    ),
    (
        "delete_image",
        re.compile(
            r"\b(delete|remove|rmi)\b[\w\s-]*\bimages?\b"
            r"|\bimages?\b[\w\s-]*\b(delete|remove)\b"
            r"|\bdocker\s+rmi\b",
            re.IGNORECASE,
        ),
        (
            "Not supported: deleting images is restricted in dockai.\n"
            "I can only inspect containers and (with confirmation) start, stop, or restart them."
        ),
    ),
    (
        "delete_volume",
        re.compile(
            r"\b(delete|remove)\b[\w\s-]*\bvolumes?\b"
            r"|\bvolumes?\b[\w\s-]*\b(delete|remove)\b",
            re.IGNORECASE,
        ),
        (
            "Not supported: deleting volumes is restricted in dockai.\n"
            "I can only inspect containers and (with confirmation) start, stop, or restart them."
        ),
    ),
    (
        "docker_desktop",
        re.compile(
            r"\b(stop|quit|close|kill|shutdown|exit)\b[\w\s-]*\bdocker\s*desktop\b"
            r"|\bdocker\s*desktop\b[\w\s-]*\b(stop|quit|close|kill|shutdown)\b",
            re.IGNORECASE,
        ),
        (
            "Not supported: Docker Desktop is the host application, not a container.\n"
            "dockai cannot stop, quit, or control Docker Desktop.\n"
            "To change a container, name it explicitly (for example: stop saien-backend-api)."
        ),
    ),
]


def check_restricted_request(user_text: str) -> Restriction | None:
    """
    If the user asked for a restricted action, return a clear refusal.

    This runs before the LLM so delete/remove cannot be reinterpreted as stop.
    """
    text = (user_text or "").strip()
    if not text:
        return None
    for kind, pattern, message in _RULES:
        if pattern.search(text):
            return Restriction(kind=kind, message=message)
    return None
