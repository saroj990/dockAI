"""Tool-calling agent loop. Docker remains the source of truth."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from collections.abc import Callable
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
For follow-ups like "that container" or "its logs", use the session focused container
only when the context marks exactly one. If unclear, ask which container.
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
    messages: list[ChatMessage] = field(default_factory=list)
    focus_container: str | None = None


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


def _names_from_tool_results(collected: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in collected:
        result = item.get("result") or {}
        if not result.get("ok"):
            continue
        data = result.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("container"), str):
                names.append(data["container"])
            if isinstance(data.get("name"), str) and "matches" not in data:
                names.append(data["name"])
            matches = data.get("matches")
            if isinstance(matches, list):
                for match in matches:
                    if isinstance(match, dict) and isinstance(match.get("name"), str):
                        names.append(match["name"])
            containers = data.get("containers")
            if isinstance(containers, list):
                for row in containers:
                    if isinstance(row, dict) and isinstance(row.get("name"), str):
                        names.append(row["name"])
        elif isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and isinstance(row.get("name"), str):
                    names.append(row["name"])
    # preserve order, unique
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _next_focus(
    collected: list[dict[str, Any]],
    previous: str | None,
) -> str | None:
    names = _names_from_tool_results(collected)
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        return None
    return previous


def _with_focus(user_text: str, focus: str | None) -> str:
    if not focus:
        return user_text
    return (
        f"{user_text}\n\n"
        f"[Session context: focused container is '{focus}'. "
        "Use it only for unambiguous references such as 'that container' or 'its logs'. "
        "If the user names a different container, use that name instead.]"
    )


def run_agent(
    user_text: str,
    *,
    llm: LLMProvider,
    client: docker.DockerClient,
    registry: dict[str, ToolSpec] | None = None,
    history: list[ChatMessage] | None = None,
    focus_container: str | None = None,
    max_turns: int = 6,
    on_progress: Callable[[str], None] | None = None,
) -> AgentResult:
    def progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    registry = registry or build_registry()
    tools = ollama_tool_schemas(registry)
    if history is None:
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
        ]
    else:
        messages = list(history)
    messages.append(
        ChatMessage(role="user", content=_with_focus(user_text, focus_container))
    )
    collected: list[dict[str, Any]] = []

    def _finish(answer: str, turns: int) -> AgentResult:
        return AgentResult(
            answer=answer,
            tool_results=collected,
            turns=turns,
            messages=messages,
            focus_container=_next_focus(collected, focus_container),
        )

    for turn in range(1, max_turns + 1):
        progress("Asking the model — please wait…")
        assistant = llm.chat(messages, tools)
        messages.append(assistant)

        if assistant.tool_calls:
            for call in assistant.tool_calls:
                progress(f"Fetching from Docker — {call.name}…")
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
            progress("Retrying with a cleaner tool call…")
            messages.append(ChatMessage(role="user", content=_NUDGE))
            continue

        progress("Almost done — preparing your answer…")
        if not answer:
            fallback = _answer_from_last_failure(collected)
            answer = fallback or (
                "I could not produce an answer. "
                "No tool result was available to summarize."
            )
        return _finish(answer, turn)

    fallback = _answer_from_last_failure(collected)
    return _finish(
        fallback
        or (
            "Stopped after the maximum number of tool rounds without a clear answer. "
            "Please retry with a more specific request."
        ),
        max_turns,
    )
