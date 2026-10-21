"""High-confidence NL shortcuts that skip Ollama for common Docker asks.

Implementation lives in ``dockai.agent.intent`` (normalize → classify → slots).
This module keeps the ``Shortcut`` / ``match_shortcut`` API used by the agent loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from dockai.agent.intent import (
    CONFIDENCE_RUN,
    NEEDS_LLM_PATTERN,
    resolve_intent,
)
from dockai.agent.scope import normalize_user_text


@dataclass(frozen=True)
class Shortcut:
    tool: str
    arguments: dict[str, Any]
    label: str


def match_shortcut(
    user_text: str,
    *,
    focus_container: str | None = None,
) -> Shortcut | None:
    """
    Return a tool call when local intent confidence is high enough to skip the LLM.
    """
    match = resolve_intent(user_text, focus_container=focus_container)
    if match.tool is None or match.confidence < CONFIDENCE_RUN:
        return None
    # Keep shortcut:* timing labels for existing tests / UX familiarity.
    label = match.label.replace("intent:", "shortcut:", 1)
    return Shortcut(tool=match.tool, arguments=match.arguments, label=label)


def needs_docker_tool(
    user_text: str,
    *,
    focus_container: str | None = None,
) -> bool:
    """
    True when this user turn should call a Docker tool (not answer from chat memory).

    Conservative: troubleshooting / explain asks return False for memory answers
    (the agent loop still may call tools via the LLM).
    """
    if match_shortcut(user_text, focus_container=focus_container) is not None:
        return True
    text = normalize_user_text(user_text)
    if not text or NEEDS_LLM_PATTERN.search(text):
        return False
    lower = text.lower()
    if re.search(
        r"\b(?:can\s+you|could\s+you|please)\s+"
        r"(?:restart|start|stop|inspect)\b",
        lower,
    ):
        return True
    if re.search(
        r"\b(?:troubleshoot|diagnos\w*|debug)\b.*\b(?:logs?|container)\b",
        lower,
    ) or re.search(
        r"\b(?:why|what).*\b(?:wrong|failing|fail|issue|problem)\b",
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
