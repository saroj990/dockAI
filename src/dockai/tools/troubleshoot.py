"""Deterministic log troubleshooting: inspect + logs + signal extraction."""

from __future__ import annotations

import re
from typing import Any

import docker

from dockai.diagnosis_summary import validate_status_for_troubleshoot
from dockai.tools.containers import get_container_logs, inspect_container

DEFAULT_TROUBLESHOOT_TAIL = 150
MAX_HIGHLIGHT_LINES = 30

# (category, pattern) — order matters for category labels on a line.
_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("traceback", re.compile(r"traceback\s+\(", re.IGNORECASE)),
    ("exception", re.compile(r"\bexception\b", re.IGNORECASE)),
    ("fatal", re.compile(r"\bfatal\b", re.IGNORECASE)),
    ("panic", re.compile(r"\bpanic\b", re.IGNORECASE)),
    ("oom", re.compile(r"\b(out of memory|oom|oomkill)\b", re.IGNORECASE)),
    ("killed", re.compile(r"\bkilled\b", re.IGNORECASE)),
    ("segfault", re.compile(r"\bsegfault\b", re.IGNORECASE)),
    ("error", re.compile(r"\berror\b", re.IGNORECASE)),
    (
        "connection",
        re.compile(r"\b(connection refused|connection reset)\b", re.IGNORECASE),
    ),
    ("permission", re.compile(r"\bpermission denied\b", re.IGNORECASE)),
    ("exit_code", re.compile(r"\bexit code\b", re.IGNORECASE)),
)


def analyze_log_text(text: str) -> dict[str, Any]:
    """
    Scan log text for high-signal lines. Never invents content — only indexes
    lines present in the input.
    """
    lines = text.splitlines()
    highlight_lines: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    has_traceback = False

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        matched: list[str] = []
        for category, pattern in _SIGNAL_PATTERNS:
            if pattern.search(line):
                matched.append(category)
                category_counts[category] = category_counts.get(category, 0) + 1
                if category == "traceback":
                    has_traceback = True
        if matched:
            highlight_lines.append(
                {
                    "line": line_no,
                    "text": line,
                    "categories": matched,
                }
            )

    if len(highlight_lines) > MAX_HIGHLIGHT_LINES:
        highlight_lines = highlight_lines[-MAX_HIGHLIGHT_LINES:]

    categories = sorted(category_counts.keys())
    return {
        "highlight_lines": highlight_lines,
        "categories": categories,
        "category_counts": category_counts,
        "has_traceback": has_traceback,
        "lines_scanned": len(lines),
        "signal_line_count": len(highlight_lines),
    }


def troubleshoot_container_logs(
    client: docker.DockerClient,
    target: str,
    *,
    tail: int | None = None,
) -> dict[str, Any]:
    """Inspect container state and analyze recent logs for troubleshooting."""
    effective_tail = tail if tail is not None else DEFAULT_TROUBLESHOOT_TAIL
    inspect_data = inspect_container(client, target)
    inspect_facts = {
        "name": inspect_data.get("name"),
        "id": inspect_data.get("id"),
        "status": inspect_data.get("status"),
        "restarts": inspect_data.get("restarts"),
        "restarting": inspect_data.get("restarting"),
        "exit_code": inspect_data.get("exit_code"),
        "oom_killed": inspect_data.get("oom_killed"),
        "error": inspect_data.get("error"),
        "health": inspect_data.get("health"),
        "uptime": inspect_data.get("uptime"),
        "image": inspect_data.get("image"),
    }
    status_validation = validate_status_for_troubleshoot(inspect_facts)
    logs_data = get_container_logs(client, target, tail=effective_tail, full=False)
    log_text = logs_data.get("logs") or ""
    analysis = analyze_log_text(log_text)

    return {
        "container": inspect_data.get("name") or target,
        "id": inspect_data.get("id"),
        "inspect": inspect_facts,
        "status_validation": status_validation,
        "logs": logs_data,
        "analysis": analysis,
    }
