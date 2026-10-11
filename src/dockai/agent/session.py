"""In-session chat state (Phase 3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import docker

from dockai.agent.loop import AgentResult, SYSTEM_PROMPT, run_agent
from dockai.llm.base import ChatMessage, LLMProvider


@dataclass
class ChatSession:
    """Keeps conversation history and an unambiguous focused container."""

    llm: LLMProvider
    client: docker.DockerClient
    messages: list[ChatMessage] = field(default_factory=list)
    focus_container: str | None = None

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
            max_turns=max_turns,
            on_progress=on_progress,
        )
        self.messages = result.messages
        self.focus_container = result.focus_container
        return result
