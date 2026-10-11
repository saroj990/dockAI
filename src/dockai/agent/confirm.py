"""User confirmation helpers for disruptive actions."""

from __future__ import annotations

_AFFIRM = frozenset(
    {
        "y",
        "yes",
        "yeah",
        "yep",
        "confirm",
        "confirmed",
        "ok",
        "okay",
        "proceed",
        "do it",
        "go ahead",
    }
)
_DENY = frozenset(
    {
        "n",
        "no",
        "nope",
        "cancel",
        "stop",
        "abort",
        "never",
    }
)


def is_affirmative(text: str) -> bool | None:
    """
    Return True / False for clear yes/no, or None if ambiguous.
    """
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return None
    if normalized in _AFFIRM:
        return True
    if normalized in _DENY:
        return False
    return None
