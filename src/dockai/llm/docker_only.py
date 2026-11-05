"""LLM stand-in when Ollama is down but Docker NL shortcuts should still work."""

from __future__ import annotations

from typing import Any

from dockai.llm.base import ChatMessage
from dockai.llm.ollama import OllamaNotFoundError


class DockerOnlyLLM:
    """
    Satisfies ChatSession when preflight failed.

    `run_agent` still handles shortcuts/help locally; this raises only when the
    model path would be required.
    """

    def close(self) -> None:
        return None

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
    ) -> ChatMessage:
        raise OllamaNotFoundError(
            "This prompt needs Ollama (model missing or host unreachable). "
            "Use Docker phrasing such as “logs for pg_tileserv”, “show running containers”, "
            "or fix the model with `dockai setup config`."
        )
