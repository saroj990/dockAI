"""Casual chat turns: LLM replies without Docker tool schemas (faster)."""

from __future__ import annotations

import re

from dockai.agent.help import is_dockai_help_request
from dockai.agent.scope import normalize_user_text
from dockai.agent.shortcuts import match_shortcut

CASUAL_SYSTEM_PROMPT = (
    "You are dockai, a concise Docker assistant. "
    "For greetings or small talk, reply briefly and warmly. "
    "Mention that you can help inspect containers, logs, uptime, and troubleshooting."
)

# Do not use the fast chat path when the user is clearly asking about Docker.
_DOCKER_INTENT_CUE = re.compile(
    r"\b("
    r"containers?|logs?|docker|inspect|uptime|restart(?:ing)?|"
    r"stop|start|image|volume|exec|troubleshoot|diagnos"
    r")\b",
    re.IGNORECASE,
)

_CASUAL_PHRASE = re.compile(
    r"^(?:"
    r"(?:hi|hello|hey|yo|howdy)(?:\s+there)?|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"how\s+are\s+you(?:\s+doing)?|"
    r"(?:thanks|thank\s+you|thx)|"
    r"(?:bye|goodbye|see\s+ya|cya)|"
    r"what(?:'?s|\s+is)\s+up|"
    r"sup"
    r")$",
    re.IGNORECASE,
)


def is_casual_chat_turn(
    user_text: str,
    *,
    focus_container: str | None = None,
) -> bool:
    """
    True when the user wants a conversational LLM reply, not Docker tools.

    Greetings and thanks skip tool schemas for faster Ollama chat.
    """
    if match_shortcut(user_text, focus_container=focus_container):
        return False
    if is_dockai_help_request(user_text):
        return False
    text = normalize_user_text(user_text).strip().rstrip("?.!")
    if not text or _DOCKER_INTENT_CUE.search(text):
        return False
    return bool(_CASUAL_PHRASE.match(text))
