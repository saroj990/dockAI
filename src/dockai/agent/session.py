"""In-session chat state (Phase 3)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import docker

from dockai.agent.loop import AgentResult, SYSTEM_PROMPT, run_agent
from dockai.agent.scope import is_bare_status_followup, normalize_user_text
from dockai.llm.base import ChatMessage, LLMProvider

_LIST_TOOLS = frozenset({"list_containers", "list_uptime", "search_containers"})


def _should_remember_list_context(user_text: str, result: AgentResult) -> bool:
    if re.search(r"\bcontainers?\b", user_text, re.IGNORECASE):
        return True
    return any(item.get("tool") in _LIST_TOOLS for item in result.tool_results)


@dataclass
class ChatSession:
    """Keeps conversation history and an unambiguous focused container."""

    llm: LLMProvider
    client: docker.DockerClient
    messages: list[ChatMessage] = field(default_factory=list)
    focus_container: str | None = None
    last_list_user_text: str | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            self.messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]

    def ask(
        self,
        user_text: str,
        *,
        max_turns: int = 6,
        on_progress: Callable[[str], None] | None = None,
    ) -> AgentResult:
        result = run_agent(
            user_text,
            llm=self.llm,
            client=self.client,
            history=self.messages,
            focus_container=self.focus_container,
            list_context=self.last_list_user_text,
            max_turns=max_turns,
            on_progress=on_progress,
        )
        self.messages = result.messages
        self.focus_container = result.focus_container
        if is_bare_status_followup(normalize_user_text(user_text)):
            pass  # keep prior list context for chained status follow-ups
        elif _should_remember_list_context(user_text, result):
            self.last_list_user_text = user_text
        else:
            self.last_list_user_text = None
        return result
