"""Tool-calling agent loop. Docker remains the source of truth."""

from __future__ import annotations

import json
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
If a tool returns ok=false, report that error honestly.
Prefer concise answers. Use tables when the user asks for tabular output.
For uptime questions, call list_uptime.
Default log window is the last 100 lines unless the user asks otherwise.
"""


@dataclass
class AgentResult:
    answer: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0


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

        if not assistant.tool_calls:
            answer = (assistant.content or "").strip()
            if not answer:
                answer = (
                    "I could not produce an answer. "
                    "No tool result was available to summarize."
                )
            return AgentResult(answer=answer, tool_results=collected, turns=turn)

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

    return AgentResult(
        answer=(
            "Stopped after the maximum number of tool rounds without a final answer. "
            "Showing the last tool result only if available is not done automatically; "
            "please retry with a more specific request."
        ),
        tool_results=collected,
        turns=max_turns,
    )
