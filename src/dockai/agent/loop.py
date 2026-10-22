"""Tool-calling agent loop. Docker remains the source of truth."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

import docker

from dockai.columns import validate_user_column_request
from dockai.agent.policy import check_restricted_request
from dockai.agent.registry import (
    ToolSpec,
    build_registry,
    execute_tool,
    ollama_tool_schemas,
)
from dockai.agent.scope import (
    apply_list_scope,
    effective_list_user_text,
    normalize_user_text,
    reconcile_tool_for_list_intent,
)
from dockai.agent.shortcuts import match_shortcut, needs_docker_tool
from dockai.llm.base import ChatMessage, LLMProvider
from dockai.present import presentation_from_tool, try_table_first

SYSTEM_PROMPT = """You are dockai, a Docker inspection assistant.
Use only the provided tools for container facts. Never invent container IDs, names,
statuses, log lines, timestamps, mounts, permissions, or success/failure.
Never invent tool results or print fake JSON that looks like a tool response
(e.g. {"ok": true, "tool": ...}). Only the tool-calling interface runs tools.
If a tool returns ok=false, call the same tool again with corrected arguments, or
briefly explain the error. Never print raw tool-call JSON to the user.
Never claim a container is missing, running, stopped, or that logs were fetched
unless a tool in this same turn returned that fact. Earlier turns may be wrong
after the user fixes a name or retries — always call a tool again.
Pass JSON types correctly: integers (25) and booleans (true/false), not strings.
Prefer concise answers. Use tables when the user asks for tabular output.
When the user asks for specific columns (e.g. only name and uptime), pass columns
on list_containers / list_uptime / search_containers.
For uptime questions, call list_uptime.
When the user asks for running containers (including "only running", "that are
running", or column subsets of running containers), call list_containers or
list_uptime with all_containers=false. For "exited/stopped/dead containers",
call list_containers with all_containers=true and status=exited|stopped|dead —
all_containers alone still includes running containers. Set all_containers=true
without status only for an explicit "all containers" ask. Do not call
get_container_logs or inspect_container for a plain list.
Default log window is the last 100 lines unless the user asks otherwise.
When the user asks for logs, log lines, tail, or to dig into logs, call
get_container_logs — not inspect_container.
When the user asks why a container is failing, restarting, unhealthy, or wants
log troubleshooting/diagnosis, you MUST call troubleshoot_container_logs before
any diagnosis answer (not get_container_logs alone, and not a narrative without
tools). Separate observed facts from hypotheses; cite log lines only if that tool
returned them. Never claim you already fixed permissions or restarted a container.
For follow-ups like "that container" or "its logs", use the session focused container
only when the context marks exactly one. If unclear, ask which container.
To start, stop, or restart a container, call start_container / stop_container /
restart_container. Those tools only propose the change; the CLI asks the user to
confirm before anything runs. Never claim you already stopped or started a container.
To run a command inside a container (docker exec), call exec_in_container. That
only proposes the command; the CLI asks the user to confirm before it runs.
Never claim you already ran docker exec or adjusted files/permissions.

Restricted (say clearly "Not supported", do not call mutation tools):
- delete/remove/rm containers, images, volumes
- prune / system cleanup
- stopping or controlling Docker Desktop (host app, not a container)
Never substitute stop/restart when the user asked to delete or remove.
Never offer to stop the focused container as an alternative to a restricted action
unless the user explicitly asks to stop that container by name.
If the user says only "yes"/"ok", only propose a mutation if your previous message
already proposed that exact start/stop/restart/exec. Otherwise ask what they want.
"""

_NUDGE = (
    "Do not print tool JSON. Use the tool-calling interface again with correct "
    "JSON types (tail as integer, full as boolean), then answer the user clearly."
)

_NUDGE_DOCKER = (
    "You must call a Docker tool in this turn before answering. Do not reuse "
    "container status or errors from earlier messages — the user may have "
    "corrected the name. Call get_container_logs, inspect_container, "
    "restart_container, or the appropriate list/search tool, then answer."
)

_NUDGE_DIAGNOSIS = (
    "This is a diagnosis ask. Call troubleshoot_container_logs with the container "
    "name/ID now (tool-calling interface). Do not invent logs, mounts, "
    "permissions, docker_exec output, or claim you already fixed or restarted "
    "anything. After the tool returns real data, summarize facts vs hypotheses."
)

_DIAGNOSIS_ASK_RE = re.compile(
    r"\b("
    r"why|how\s+come|troubleshoot|diagnos|"
    r"what('?s|\s+is|\s+could|\s+might)\s+wrong|"
    r"failing|broken|unhealthy|restarting"
    r")\b",
    re.IGNORECASE,
)

_STALE_DOCKER_CLAIM_RE = re.compile(
    r"\b("
    r"not\s+found|does\s+not\s+exist|doesn't\s+exist|no\s+container|"
    r"could\s+not\s+find|unable\s+to\s+find|cannot\s+find|can't\s+find|"
    r"missing\s+container|container\s+is\s+(?:not\s+)?(?:running|stopped|exited)"
    r")\b",
    re.IGNORECASE,
)

_TOOL_DUMP_RE = re.compile(
    r'(\{[^{}]*"name"\s*:\s*"[a-z_]+"[^{}]*"parameters"\s*:)|'
    r'(\{[^{}]*"parameters"\s*:\s*\{[^{}]*"target")',
    re.IGNORECASE | re.DOTALL,
)

# Hallucinated "I already ran tools" narratives (common with weak local models).
_FABRICATED_TOOL_RE = re.compile(
    r"("
    r'"ok"\s*:\s*true|'
    r'"tool"\s*:\s*"|'
    r"\bdocker_exec\b|"
    r"```json|"
    r"\bI\s+(?:have\s+)?(?:already\s+)?(?:adjusted|fixed|restarted|ran)\b|"
    r"\bAfter\s+fixing\b|"
    r"\bStep\s+\d+\s*:"
    r")",
    re.IGNORECASE,
)


@dataclass
class AgentResult:
    answer: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    messages: list[ChatMessage] = field(default_factory=list)
    focus_container: str | None = None
    pending_action: dict[str, Any] | None = None
    # Stage timings: (label, seconds) — used to explain NL latency.
    timings: list[tuple[str, float]] = field(default_factory=list)
    # When set, CLI renders Rich output from Docker and skips LLM narration.
    presentation: dict[str, Any] | None = None


def _is_diagnosis_ask(user_text: str) -> bool:
    text = normalize_user_text(user_text)
    return bool(text and _DIAGNOSIS_ASK_RE.search(text))


def _has_successful_troubleshoot(collected: list[dict[str, Any]]) -> bool:
    return any(
        item.get("tool") == "troubleshoot_container_logs"
        and (item.get("result") or {}).get("ok")
        for item in collected
    )


def _should_nudge_missing_docker_call(
    user_text: str,
    *,
    focus_container: str | None,
    collected: list[dict[str, Any]],
    answer: str,
) -> bool:
    if collected:
        return False
    if needs_docker_tool(user_text, focus_container=focus_container):
        return True
    return bool(_STALE_DOCKER_CLAIM_RE.search(answer or ""))


def _should_nudge_diagnosis(
    user_text: str,
    *,
    collected: list[dict[str, Any]],
    answer: str,
) -> bool:
    """Diagnosis answers require a real troubleshoot_container_logs result."""
    if not _is_diagnosis_ask(user_text):
        return False
    if _has_successful_troubleshoot(collected):
        return False
    # Always nudge until the tool runs — including fake JSON narratives.
    return True


def _looks_like_tool_dump(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _TOOL_DUMP_RE.search(stripped):
        return True
    if _FABRICATED_TOOL_RE.search(stripped):
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
            nested = data.get("container")
            if isinstance(nested, dict) and isinstance(nested.get("name"), str):
                names.append(nested["name"])
            if isinstance(data.get("name"), str) and "matches" not in data:
                names.append(data["name"])
            if isinstance(data.get("target"), str) and data.get("needs_confirmation"):
                names.append(data["target"])
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


def _pending_from_results(collected: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(collected):
        result = item.get("result") or {}
        data = result.get("data")
        if result.get("ok") and isinstance(data, dict) and data.get("needs_confirmation"):
            return data
    return None


def _format_pending(pending: dict[str, Any]) -> str:
    container = pending.get("container") or {}
    return (
        f"{pending.get('message', 'Confirmation required.')}\n"
        f"Impact: {pending.get('impact', '')}\n"
        f"Name: {container.get('name')} | ID: {container.get('id')} | "
        f"Status: {container.get('status')}\n"
        "Confirm in the prompt to proceed (nothing has been changed yet)."
    )


def _with_focus(user_text: str, focus: str | None) -> str:
    if not focus:
        return user_text
    return (
        f"{user_text}\n\n"
        f"[Session context: focused container is '{focus}'. "
        "Use it only for unambiguous references such as 'that container' or 'its logs'. "
        "If the user names a different container, use that name instead. "
        "Do not use the focused container to reinterpret delete/remove/prune requests.]"
    )


def run_agent(
    user_text: str,
    *,
    llm: LLMProvider,
    client: docker.DockerClient,
    registry: dict[str, ToolSpec] | None = None,
    history: list[ChatMessage] | None = None,
    focus_container: str | None = None,
    list_context: str | None = None,
    max_turns: int = 6,
    on_progress: Callable[[str], None] | None = None,
) -> AgentResult:
    def progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    if history is None:
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
        ]
    else:
        messages = list(history)

    # Deterministic gate: refuse restricted asks before the LLM can mis-route them.
    restriction = check_restricted_request(user_text)
    if restriction is not None:
        progress("Request is restricted — explaining clearly…")
        messages.append(ChatMessage(role="user", content=user_text))
        messages.append(
            ChatMessage(role="assistant", content=restriction.message)
        )
        return AgentResult(
            answer=restriction.message,
            tool_results=[],
            turns=0,
            messages=messages,
            focus_container=focus_container,
            pending_action=None,
            timings=[],
            presentation=None,
        )

    validate_user_column_request(user_text)

    list_text = effective_list_user_text(user_text, list_context)

    registry = registry or build_registry()
    tools = ollama_tool_schemas(registry)
    messages.append(
        ChatMessage(role="user", content=_with_focus(user_text, focus_container))
    )
    collected: list[dict[str, Any]] = []
    timings: list[tuple[str, float]] = []
    pending_presentation: dict[str, Any] | None = None

    def _finish(
        answer: str,
        turns: int,
        *,
        presentation: dict[str, Any] | None = None,
    ) -> AgentResult:
        pending = _pending_from_results(collected)
        resolved_presentation = (
            presentation if presentation is not None else pending_presentation
        )
        return AgentResult(
            answer=answer,
            tool_results=collected,
            turns=turns,
            messages=messages,
            focus_container=_next_focus(collected, focus_container),
            pending_action=pending,
            timings=list(timings),
            presentation=resolved_presentation,
        )

    # High-confidence phrases skip Ollama entirely.
    shortcut = match_shortcut(list_text, focus_container=focus_container)
    if shortcut is not None:
        progress(f"NL shortcut matched ({shortcut.label}) — skipping Ollama…")
        shortcut_args = apply_list_scope(
            list_text, shortcut.tool, shortcut.arguments
        )
        t0 = time.perf_counter()
        result = execute_tool(
            registry, client, shortcut.tool, shortcut_args
        )
        timings.append((shortcut.label, time.perf_counter() - t0))
        item = {
            "tool": shortcut.tool,
            "arguments": shortcut_args,
            "result": result,
        }
        collected.append(item)
        messages.append(
            ChatMessage(
                role="assistant",
                content=f"[nl-shortcut] {shortcut.tool}",
            )
        )
        messages.append(
            ChatMessage(
                role="tool",
                name=shortcut.tool,
                content=json.dumps(result, default=str),
            )
        )
        pending = _pending_from_results(collected)
        if pending is not None:
            return _finish(_format_pending(pending), 0)
        if result.get("ok"):
            direct = try_table_first([item], user_text=list_text)
            if direct is not None:
                messages.append(
                    ChatMessage(role="assistant", content=direct["caption"])
                )
                return _finish(direct["caption"], 0, presentation=direct)
            return _finish(
                json.dumps(result.get("data"), default=str)[:2000],
                0,
            )
        return _finish(
            f"I could not complete that request: {result.get('error', 'unknown error')}",
            0,
        )

    model_calls = 0
    for turn in range(1, max_turns + 1):
        progress("Asking the model — please wait…")
        model_calls += 1
        t0 = time.perf_counter()
        assistant = llm.chat(messages, tools)
        timings.append((f"ollama #{model_calls}", time.perf_counter() - t0))
        messages.append(assistant)

        if assistant.tool_calls:
            batch: list[dict[str, Any]] = []
            for call in assistant.tool_calls:
                progress(f"Fetching from Docker — {call.name}…")
                tool_name, call_args = reconcile_tool_for_list_intent(
                    user_text,
                    call.name,
                    call.arguments,
                    list_context=list_context,
                )
                t1 = time.perf_counter()
                result = execute_tool(registry, client, tool_name, call_args)
                timings.append((f"docker {tool_name}", time.perf_counter() - t1))
                item = {
                    "tool": tool_name,
                    "arguments": call_args,
                    "result": result,
                }
                batch.append(item)
                collected.append(item)
                messages.append(
                    ChatMessage(
                        role="tool",
                        name=tool_name,
                        tool_call_id=call.id,
                        content=json.dumps(result, default=str),
                    )
                )
            # Skip a second LLM hop for mutation proposals (faster + safer).
            pending = _pending_from_results(batch)
            if pending is not None:
                progress("Waiting for your confirmation…")
                return _finish(_format_pending(pending), turn)

            if (
                len(batch) == 1
                and batch[0].get("tool") == "troubleshoot_container_logs"
                and (batch[0].get("result") or {}).get("ok")
            ):
                built = presentation_from_tool(
                    "troubleshoot_container_logs",
                    batch[0]["result"].get("data"),
                )
                if built is not None:
                    pending_presentation = built
                progress("Log signals ready — asking the model to summarize…")
                continue

            # Skip summarization LLM for simple list/logs/search/inspect.
            direct = try_table_first(batch, user_text=list_text)
            if direct is not None:
                progress("Rendering Docker results (skipping model summary)…")
                caption = direct["caption"]
                messages.append(ChatMessage(role="assistant", content=caption))
                return _finish(caption, turn, presentation=direct)
            continue

        answer = (assistant.content or "").strip()
        if _looks_like_tool_dump(answer):
            grounded = _has_successful_troubleshoot(collected)
            classic_dump = bool(
                _TOOL_DUMP_RE.search(answer)
                or (answer.startswith("{") and "parameters" in answer)
            )
            # After real troubleshoot evidence, allow a prose summary even if it
            # says "step" / "fixed" casually; still reject raw tool-call dumps.
            if not (grounded and not classic_dump):
                if _is_diagnosis_ask(user_text) and not grounded:
                    progress("Retrying — diagnosis needs real Docker evidence…")
                    messages.append(
                        ChatMessage(role="user", content=_NUDGE_DIAGNOSIS)
                    )
                else:
                    progress("Retrying with a cleaner tool call…")
                    messages.append(ChatMessage(role="user", content=_NUDGE))
                continue

        if _should_nudge_diagnosis(
            user_text,
            collected=collected,
            answer=answer,
        ):
            progress("Diagnosis requires troubleshoot_container_logs — retrying…")
            messages.append(ChatMessage(role="user", content=_NUDGE_DIAGNOSIS))
            continue

        if _should_nudge_missing_docker_call(
            user_text,
            focus_container=focus_container,
            collected=collected,
            answer=answer,
        ):
            progress("Model answered without calling Docker — retrying with a tool…")
            messages.append(ChatMessage(role="user", content=_NUDGE_DOCKER))
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
    if _is_diagnosis_ask(user_text) and not _has_successful_troubleshoot(collected):
        return _finish(
            fallback
            or (
                "I could not gather Docker evidence for this diagnosis "
                "(troubleshoot_container_logs did not run successfully). "
                "Try: dockai logs <container> — or retry with a tool-capable model."
            ),
            max_turns,
        )
    return _finish(
        fallback
        or (
            "Stopped after the maximum number of tool rounds without a clear answer. "
            "Please retry with a more specific request."
        ),
        max_turns,
    )
