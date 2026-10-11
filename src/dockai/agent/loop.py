"""Tool-calling agent loop. Docker remains the source of truth."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import docker

from dockai.agent.registry import (
    ToolSpec,
    build_registry,
    execute_tool,
    ollama_tool_schemas,
)
from dockai.llm.base import ChatMessage, LLMProvider

SYSTEM_PROMPT = """You are dockai, a Docker inspection assistant.
Use only the provided tools for container facts. Never invent container IDs, names,
statuses, log lines, timestamps, or success/failure.
If a tool returns ok=false, call the same tool again with corrected arguments, or
briefly explain the error. Never print raw tool-call JSON to the user.
Pass JSON types correctly: integers (25) and booleans (true/false), not strings.
Prefer concise answers. Use tables when the user asks for tabular output.
For uptime questions, call list_uptime.
Default log window is the last 100 lines unless the user asks otherwise.
"""

_NUDGE = (
    "Do not print tool JSON. Use the tool-calling interface again with correct "
    "JSON types (tail as integer, full as boolean), then answer the user clearly."
)

_TOOL_DUMP_RE = re.compile(
    r'(\{[^{}]*"name"\s*:\s*"[a-z_]+"[^{}]*"parameters"\s*:)|'
    r'(\{[^{}]*"parameters"\s*:\s*\{[^{}]*"target")',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class AgentResult:
    answer: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0


def _looks_like_tool_dump(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _TOOL_DUMP_RE.search(stripped):
        return True
    if stripped.startswith("{") and "parameters" in stripped:
        return True
    return (
        "Let me try again" in stripped
        and "{" in stripped
        and "parameters" in stripped
    )


def _answer_from_last_failure(collected: list[dict[str, Any]]) -> str | None:
    if not collected:
        return None
    last = collected[-1].get("result") or {}
    if last.get("ok") is False and last.get("error"):
        return f"I could not complete that request: {last['error']}"
    return None


def run_agent(
    user_text: str,
    *,
    llm: LLMProvider,
    client: docker.DockerClient,
    registry: dict[str, ToolSpec] | None = None,
    max_turns: int = 6,
) -> AgentResult:
    registry = registry or build_registry()
    tools = ollama_tool_schemas(registry)
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_text),
    ]
    collected: list[dict[str, Any]] = []

    for turn in range(1, max_turns + 1):
        assistant = llm.chat(messages, tools)
        messages.append(assistant)

        if assistant.tool_calls:
            for call in assistant.tool_calls:
                result = execute_tool(registry, client, call.name, call.arguments)
                collected.append(
                    {"tool": call.name, "arguments": call.arguments, "result": result}
                )
                messages.append(
                    ChatMessage(
                        role="tool",
                        name=call.name,
                        tool_call_id=call.id,
                        content=json.dumps(result, default=str),
                    )
                )
            continue

        answer = (assistant.content or "").strip()
        if _looks_like_tool_dump(answer):
            messages.append(ChatMessage(role="user", content=_NUDGE))
            continue

        if not answer:
            fallback = _answer_from_last_failure(collected)
            answer = fallback or (
                "I could not produce an answer. "
                "No tool result was available to summarize."
            )
            return AgentResult(answer=answer, tool_results=collected, turns=turn)

        return AgentResult(answer=answer, tool_results=collected, turns=turn)

    fallback = _answer_from_last_failure(collected)
    return AgentResult(
        answer=fallback
        or (
            "Stopped after the maximum number of tool rounds without a clear answer. "
            "Please retry with a more specific request."
        ),
        tool_results=collected,
        turns=max_turns,
    )
