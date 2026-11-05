"""Deterministic diagnosis copy from troubleshoot inspect + log signals."""

from __future__ import annotations

import re
from typing import Any

_RESTART_ASK_RE = re.compile(
    r"\b(?:restart(?:ing|s|ed)?|crash(?:ing|es|ed)?|keep(?:s)?\s+restart)\b",
    re.IGNORECASE,
)

_SHUTDOWN_RE = re.compile(
    r"administrator command|terminating background worker",
    re.IGNORECASE,
)
_LOG_MSG_RE = re.compile(r'msg="([^"]+)"', re.IGNORECASE)
_FAILED_CONNECT_HOST_RE = re.compile(
    r"failed to connect to\s+`([^`]+)`",
    re.IGNORECASE,
)


def user_asks_restart_or_crash_loop(user_text: str) -> bool:
    text = (user_text or "").strip()
    return bool(text and _RESTART_ASK_RE.search(text))


def is_active_restart_loop(inspect: dict[str, Any]) -> bool:
    if inspect.get("restarting") is True:
        return True
    restarts = inspect.get("restarts")
    try:
        count = int(restarts) if restarts is not None else 0
    except (TypeError, ValueError):
        count = 0
    status = str(inspect.get("status") or "").lower()
    if count > 0 and status in {"restarting", "exited", "dead"}:
        return True
    return status == "restarting"


def validate_status_for_troubleshoot(inspect: dict[str, Any]) -> dict[str, Any]:
    """
    Assess Docker state from inspect before log analysis is interpreted.

    Called immediately after inspect in troubleshoot_container_logs.
    """
    status = str(inspect.get("status") or "").lower()
    restarting = inspect.get("restarting") is True
    try:
        restarts = int(inspect.get("restarts") or 0)
    except (TypeError, ValueError):
        restarts = 0
    return {
        "status": status,
        "restarting": restarting,
        "restarts": restarts,
        "active_restart_loop": is_active_restart_loop(inspect),
        "ready_for_log_analysis": status in {
            "running",
            "restarting",
            "exited",
            "dead",
            "paused",
        },
    }


def _uptime_display(inspect: dict[str, Any]) -> str | None:
    uptime = inspect.get("uptime")
    if isinstance(uptime, dict):
        value = uptime.get("value")
        if value:
            return str(value)
    if isinstance(uptime, str) and uptime.strip():
        return uptime.strip()
    return None


def format_inspect_fact_lines(inspect: dict[str, Any]) -> list[str]:
    """Tool-backed inspect facts for the opening of a diagnosis answer."""
    name = inspect.get("name") or inspect.get("container") or "container"
    lines = [f"Docker inspect for {name}:"]
    status = inspect.get("status")
    if status is not None:
        lines.append(f"- Status: {status}")
    restarts = inspect.get("restarts")
    if restarts is not None:
        lines.append(f"- Restarts: {restarts}")
    if inspect.get("restarting") is not None:
        lines.append(f"- Restarting: {inspect.get('restarting')}")
    health = inspect.get("health")
    if health is not None:
        lines.append(f"- Health: {health}")
    uptime = _uptime_display(inspect)
    if uptime:
        lines.append(f"- Uptime: {uptime}")
    exit_code = inspect.get("exit_code")
    if exit_code is not None and exit_code != 0:
        lines.append(f"- Exit code: {exit_code}")
    if inspect.get("oom_killed"):
        lines.append("- OOM killed: True")
    if inspect.get("error"):
        lines.append(f"- Docker error: {inspect.get('error')}")
    return lines


def _log_lines_look_historical_shutdown(highlights: list[dict[str, Any]]) -> bool:
    for item in highlights:
        text = item.get("text") or ""
        if _SHUTDOWN_RE.search(text):
            return True
    return False


def extract_plain_language_findings(analysis: dict[str, Any]) -> list[str]:
    """
    Short, user-facing lines distilled from log highlights (deduped).
    """
    highlights = analysis.get("highlight_lines") or []
    findings: list[str] = []
    seen: set[str] = set()

    for item in highlights:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        lower = text.lower()
        candidate: str | None = None

        msg_match = _LOG_MSG_RE.search(text)
        if msg_match:
            candidate = msg_match.group(1).strip()
        elif _FAILED_CONNECT_HOST_RE.search(text):
            candidate = _FAILED_CONNECT_HOST_RE.search(text).group(0).strip()

        if candidate is None and "fatal" in lower:
            candidate = text.split("level=fatal", 1)[-1].strip() if "level=fatal" in lower else text
            if len(candidate) > 220:
                candidate = candidate[:217] + "…"

        if candidate is None:
            if "connection refused" in lower:
                candidate = "A connection was refused — the target host/port is not accepting connections."
            elif "network is unreachable" in lower:
                candidate = "A network connection failed (network is unreachable)."
            elif "permission denied" in lower:
                candidate = "Permission denied in the logs."
            elif "panic:" in lower:
                candidate = text[text.lower().find("panic:") :].strip()[:200]

        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        findings.append(candidate)
        if len(findings) >= 3:
            break

    return findings


def has_plain_language_findings(analysis: dict[str, Any]) -> bool:
    return bool(extract_plain_language_findings(analysis))


def format_plain_language_section(analysis: dict[str, Any]) -> str:
    findings = extract_plain_language_findings(analysis)
    if not findings:
        return ""
    lines = ["What the logs say (plain language):"]
    for finding in findings:
        lines.append(f"- {finding}")
    return "\n".join(lines)


def summarize_log_issues(
    analysis: dict[str, Any],
    *,
    inspect: dict[str, Any],
) -> str:
    """What could be wrong, grounded in categorized log signals only."""
    highlights = analysis.get("highlight_lines") or []
    if not highlights:
        return (
            "Log scan: no error-like lines in the analyzed tail — "
            "nothing obvious in recent logs."
        )

    categories = analysis.get("categories") or []
    parts: list[str] = []
    if "fatal" in categories:
        parts.append("FATAL messages")
    if "error" in categories:
        parts.append("ERROR messages")
    if "oom" in categories or "killed" in categories:
        parts.append("memory/OOM signals")
    if "panic" in categories:
        parts.append("panic lines")
    if "connection" in categories:
        parts.append("connection failures")
    if "traceback" in categories or analysis.get("has_traceback"):
        parts.append("Python tracebacks")
    if not parts:
        parts.append("high-signal log lines")

    line = (
        f"Log scan ({analysis.get('signal_line_count', len(highlights))} signal line(s)): "
        f"possible issues from logs include {', '.join(parts)}."
    )

    specifics: list[str] = []
    for item in highlights[:8]:
        text = (item.get("text") or "").strip()
        lower = text.lower()
        if "postgis_version" in lower or "postgis" in lower and "does not exist" in lower:
            specifics.append(
                "PostGIS function/extension errors — PostGIS may be missing or wrong version."
            )
        if _SHUTDOWN_RE.search(text):
            specifics.append(
                "Worker shutdown / administrator command lines (often from stop or restart)."
            )
        if (
            "connection refused" in lower
            or "connection reset" in lower
            or "network is unreachable" in lower
            or "failed to connect" in lower
        ):
            specifics.append(
                "Database or service connection failures — check host/port in config."
            )
        if "permission denied" in lower:
            specifics.append("Permission denied — file or socket permissions.")

    if specifics:
        seen: set[str] = set()
        ordered: list[str] = []
        for s in specifics:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        line += " " + " ".join(ordered)

    if (
        _log_lines_look_historical_shutdown(highlights)
        and not is_active_restart_loop(inspect)
    ):
        line += (
            " Some FATAL lines look like past shutdowns; "
            "compare timestamps to current uptime — Docker does not show a crash loop now."
        )

    return line


def build_diagnosis_answer(user_text: str, troubleshoot_data: dict[str, Any]) -> str:
    """Fact-first diagnosis text from troubleshoot_container_logs payload."""
    inspect = troubleshoot_data.get("inspect") or {}
    analysis = troubleshoot_data.get("analysis") or {}
    blocks: list[str] = []
    blocks.extend(format_inspect_fact_lines(inspect))

    if user_asks_restart_or_crash_loop(user_text) and not is_active_restart_loop(
        inspect
    ):
        blocks.append(
            "Docker does not show an active restart loop right now "
            "(Restarting=false; see restart count above)."
        )

    if is_active_restart_loop(inspect):
        blocks.append(
            "Docker reports a restart problem (restarting state and/or elevated restarts)."
        )

    blocks.append(summarize_log_issues(analysis, inspect=inspect))
    plain = format_plain_language_section(analysis)
    if plain:
        blocks.append(plain)
    likely = _likely_cause_from_findings(analysis, inspect=inspect)
    if likely:
        blocks.append(likely)
    return "\n".join(blocks)


def _likely_cause_from_findings(
    analysis: dict[str, Any],
    *,
    inspect: dict[str, Any],
) -> str:
    """One-line hypothesis grounded in repeated log text (not generic Docker advice)."""
    joined = " ".join(extract_plain_language_findings(analysis)).lower()
    if not joined:
        return ""
    if "host.docker.internal" in joined and (
        "failed to connect" in joined or "network is unreachable" in joined
    ):
        name = inspect.get("name") or "This container"
        return (
            f"Likely cause: {name} is pointed at Postgres on the host "
            "(`host.docker.internal`), but nothing is reachable there from this "
            "container — use your Compose DB service (e.g. `db`) on the internal network."
        )
    if inspect.get("oom_killed"):
        return "Likely cause: the container was killed for memory (OOM)."
    if "connection refused" in joined:
        return (
            "Likely cause: the app cannot reach the database or upstream service "
            "at the configured host/port."
        )
    return ""


def should_finish_diagnosis_without_llm(
    user_text: str, troubleshoot_data: dict[str, Any]
) -> bool:
    """Skip the summarization LLM when facts + log wording are enough."""
    analysis = troubleshoot_data.get("analysis")
    if isinstance(analysis, dict) and has_plain_language_findings(analysis):
        return True
    if not user_asks_restart_or_crash_loop(user_text):
        return False
    inspect = troubleshoot_data.get("inspect")
    if not isinstance(inspect, dict):
        return False
    return not is_active_restart_loop(inspect)


def merge_diagnosis_answer(prefix: str, llm_answer: str) -> str:
    """Prepend deterministic facts when an LLM summary follows troubleshoot."""
    body = (llm_answer or "").strip()
    if not body:
        return prefix.strip()
    if body.startswith(prefix.strip()[:40]):
        return body
    return f"{prefix.strip()}\n\n{body}"
