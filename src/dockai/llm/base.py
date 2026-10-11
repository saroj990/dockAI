"""Provider-agnostic LLM types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class LLMProvider(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
    ) -> ChatMessage:
        """Return the next assistant message (text and/or tool calls)."""
        ...
