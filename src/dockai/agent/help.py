"""Deterministic answers for “what can I run in dockai?” meta questions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources

# Meta asks about dockai itself — not “what is wrong with my container”.
_DOCKAI_HELP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bwhat\s+(?:are\s+)?(?:the\s+)?commands?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+commands?\s+(?:are\s+there|can\s+i\s+run|do\s+you\s+(?:have|support)|exist)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:show|list|tell\s+me)\s+(?:me\s+)?(?:the\s+)?(?:available\s+)?commands?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blist\s+(?:all\s+)?(?:dockai\s+)?commands?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+can\s+(?:i\s+run|dockai\s+do)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhow\s+(?:do\s+i\s+use|to\s+use)\s+dockai\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:dockai|your)\s+commands?\b.*\b(?:available|list|show)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcommands?\s+i\s+can\s+run\b",
        re.IGNORECASE,
    ),
)

# Exclude Docker CLI help / unrelated “what is …” container asks.
_EXCLUDE_HELP = re.compile(
    r"\b(?:docker\s+(?:ps|run|rm|images?|compose)|kubectl|kubernetes)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DockaiHelpResponse:
    markdown: str
    plain_intro: str = "Here are the dockai commands and example questions you can use."


def is_dockai_help_request(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text or _EXCLUDE_HELP.search(text):
        return False
    return any(p.search(text) for p in _DOCKAI_HELP_PATTERNS)


def load_commands_help_markdown() -> str:
    return (
        resources.files("dockai.data")
        .joinpath("commands_help.md")
        .read_text(encoding="utf-8")
    )


def try_dockai_help_response(user_text: str) -> DockaiHelpResponse | None:
    if not is_dockai_help_request(user_text):
        return None
    return DockaiHelpResponse(markdown=load_commands_help_markdown())
