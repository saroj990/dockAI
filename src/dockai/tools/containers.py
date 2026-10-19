"""Read-only container tools using the Docker SDK."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from dockai.errors import (
    AmbiguousContainerError,
    ContainerNotFoundError,
    DockerUnavailableError,
)
from dockai.uptime import compute_uptime

DEFAULT_LOG_TAIL = 100
# Soft cap so "full logs" cannot flood the terminal or LLM context later.
MAX_FULL_LOG_CHARS = 200_000

# User-facing status filter keys → Docker State.Status values.
STATUS_FILTERS: dict[str, frozenset[str]] = {
    "running": frozenset({"running"}),
    "exited": frozenset({"exited"}),
    "stopped": frozenset({"exited", "dead"}),
    "dead": frozenset({"dead"}),
    "not_running": frozenset({"created", "exited", "dead", "paused"}),
}


def _apply_status_filter(
    rows: list[dict[str, Any]], status: str | None
) -> list[dict[str, Any]]:
    if not status:
        return rows
    if status == "not_running":
        return [
            row
            for row in rows
            if (row.get("status") or "").lower() != "running"
        ]
    if status not in STATUS_FILTERS:
        raise ValueError(
            f"Unknown status filter '{status}'. "
            f"Use one of: {', '.join(sorted(STATUS_FILTERS))}."
        )
    allowed = STATUS_FILTERS[status]
    return [row for row in rows if (row.get("status") or "").lower() in allowed]

# Close-match (typo) resolution — conservative to avoid wrong container ops.
_FUZZY_MIN_NORM_LEN = 6
_FUZZY_MAX_EDIT_DISTANCE = 2
_FUZZY_MIN_RATIO = 0.84
_HEX_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")


def _short_id(container_id: str) -> str:
    return container_id[:12]


def _primary_name(container: Container) -> str:
    names = container.attrs.get("Names") or container.name
    if isinstance(names, list) and names:
        return names[0].lstrip("/")
    if container.name:
        return container.name.lstrip("/")
    return _short_id(container.id)


def _state_dict(container: Container) -> dict[str, Any]:
    return container.attrs.get("State") or {}


def summarize_container(container: Container) -> dict[str, Any]:
    """Build a structured summary from Docker attrs (no invented fields)."""
    state = _state_dict(container)
    status = state.get("Status") or container.status or "unknown"
    started_at = state.get("StartedAt")
    finished_at = state.get("FinishedAt")
    uptime = compute_uptime(
        status=status,
        started_at=started_at,
        finished_at=finished_at,
    )
    image = container.image.tags[0] if container.image.tags else (
        container.attrs.get("Config", {}).get("Image")
        or (container.image.short_id if container.image else "unknown")
    )
    return {
        "id": _short_id(container.id),
        "full_id": container.id,
        "name": _primary_name(container),
        "status": status,
        "image": image,
        "restarting": bool(state.get("Restarting")),
        "restarts": int(state.get("RestartCount") or 0),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "error": state.get("Error") or None,
        "started_at": started_at,
        "finished_at": finished_at,
        "uptime": uptime,
    }


def list_containers(
    client: docker.DockerClient,
    *,
    all_containers: bool = False,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """
    List containers; defaults to running only.

    Optional status filter key: running | exited | stopped | dead | not_running.
    "stopped" matches Docker exited + dead. "not_running" excludes running status.
    """
    if status == "not_running":
        all_containers = True
    try:
        containers = client.containers.list(all=all_containers)
    except APIError as exc:
        raise DockerUnavailableError(f"Failed to list containers: {exc}") from exc
    rows = [summarize_container(c) for c in containers]
    return _apply_status_filter(rows, status)


def _normalize_name(value: str) -> str:
    """Collapse case/separators so 'saien backend api' matches 'saien-backend-api'."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _looks_like_container_id(target: str) -> bool:
    """True for hex-like IDs — never fuzzy-match these."""
    return bool(_HEX_ID_RE.fullmatch(target.strip().lower()))


def _edit_distance(a: str, b: str, *, max_dist: int) -> int | None:
    """
    Levenshtein distance with early exit.

    Returns None when distance would exceed max_dist (or length gap alone does).
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_dist:
        return None
    # Ensure a is the shorter string for fewer rows.
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for i, ch_b in enumerate(b, start=1):
        curr = [i]
        row_min = i
        for j, ch_a in enumerate(a, start=1):
            ins = curr[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ch_a == ch_b else 1)
            val = min(ins, delete, sub)
            curr.append(val)
            if val < row_min:
                row_min = val
        if row_min > max_dist:
            return None
        prev = curr
    dist = prev[-1]
    return dist if dist <= max_dist else None


def _fuzzy_close_matches(
    containers: list[Container],
    *,
    target: str,
    target_n: str,
) -> list[Container]:
    """
    Name-only typo candidates after exact/partial matching failed.

    Safety: no ID fuzzing, min normalized length, max edit distance, min ratio.
    Multiple survivors → caller treats as ambiguous (never silent pick).
    """
    if _looks_like_container_id(target):
        return []
    if len(target_n) < _FUZZY_MIN_NORM_LEN:
        return []

    scored: list[tuple[float, int, Container]] = []
    for container in containers:
        name = _primary_name(container)
        name_n = _normalize_name(name)
        if len(name_n) < _FUZZY_MIN_NORM_LEN:
            continue
        dist = _edit_distance(
            target_n, name_n, max_dist=_FUZZY_MAX_EDIT_DISTANCE
        )
        if dist is None:
            continue
        ratio = SequenceMatcher(None, target_n, name_n).ratio()
        if ratio < _FUZZY_MIN_RATIO:
            continue
        scored.append((ratio, dist, container))

    if not scored:
        return []
    # Prefer higher ratio, then lower edit distance.
    scored.sort(key=lambda item: (-item[0], item[1], _primary_name(item[2])))
    # Only keep those within the same quality band as the best match so a
    # distant second does not inflate ambiguity noise — but if two are both
    # above threshold, return both (safer than auto-picking).
    best_ratio, best_dist, _ = scored[0]
    close = [
        c
        for ratio, dist, c in scored
        if ratio >= _FUZZY_MIN_RATIO
        and dist <= _FUZZY_MAX_EDIT_DISTANCE
        and (best_ratio - ratio) <= 0.05
        and dist <= best_dist + 1
    ]
    return close


def _match_candidates(
    client: docker.DockerClient,
    target: str,
    *,
    all_containers: bool = True,
) -> list[Container]:
    target_l = target.strip().lower()
    target_n = _normalize_name(target)
    try:
        containers = client.containers.list(all=all_containers)
    except APIError as exc:
        raise DockerUnavailableError(f"Failed to list containers: {exc}") from exc

    exact: list[Container] = []
    exact_norm: list[Container] = []
    partial: list[Container] = []
    partial_norm: list[Container] = []
    for container in containers:
        name = _primary_name(container).lower()
        name_n = _normalize_name(name)
        cid = container.id.lower()
        short = _short_id(container.id).lower()
        if name == target_l or cid == target_l or short == target_l:
            exact.append(container)
        elif target_n and name_n == target_n:
            exact_norm.append(container)
        elif target_l and (target_l in name or cid.startswith(target_l)):
            partial.append(container)
        elif len(target_n) >= 3 and target_n in name_n:
            partial_norm.append(container)

    strict = exact or exact_norm or partial or partial_norm
    if strict:
        return strict
    return _fuzzy_close_matches(
        containers, target=target, target_n=target_n
    )


def resolve_container(
    client: docker.DockerClient,
    target: str,
    *,
    all_containers: bool = True,
) -> Container:
    """Resolve a name/ID to exactly one container (incl. conservative typo match)."""
    matches = _match_candidates(client, target, all_containers=all_containers)
    if not matches:
        # Fall back to Docker's native lookup for exact IDs/names.
        try:
            return client.containers.get(target)
        except NotFound as exc:
            raise ContainerNotFoundError(
                f"No container matched '{target}'."
            ) from exc
        except APIError as exc:
            raise DockerUnavailableError(f"Docker error: {exc}") from exc

    if len(matches) > 1:
        raise AmbiguousContainerError(
            f"Multiple containers matched '{target}'. Choose one.",
            matches=[summarize_container(c) for c in matches],
        )
    return matches[0]


def inspect_container(
    client: docker.DockerClient,
    target: str,
) -> dict[str, Any]:
    """Inspect a single container by name or ID."""
    container = resolve_container(client, target)
    try:
        container.reload()
    except APIError as exc:
        raise DockerUnavailableError(f"Failed to inspect container: {exc}") from exc
    summary = summarize_container(container)
    state = _state_dict(container)
    summary["health"] = (state.get("Health") or {}).get("Status")
    summary["pid"] = state.get("Pid")
    return summary


def get_container_logs(
    client: docker.DockerClient,
    target: str,
    *,
    tail: int | None = DEFAULT_LOG_TAIL,
    full: bool = False,
) -> dict[str, Any]:
    """
    Retrieve container logs.

    Default: last 100 lines.
    full=True: all logs available via Docker, subject to MAX_FULL_LOG_CHARS.
    """
    if full and tail is not None and tail != DEFAULT_LOG_TAIL:
        raise ValueError("Use either --full or --tail, not both with a custom count.")

    container = resolve_container(client, target)
    name = _primary_name(container)

    try:
        if full:
            raw = container.logs(stdout=True, stderr=True, timestamps=False)
            truncated = False
            text = raw.decode("utf-8", errors="replace")
            if len(text) > MAX_FULL_LOG_CHARS:
                text = text[-MAX_FULL_LOG_CHARS:]
                truncated = True
            line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            return {
                "container": name,
                "id": _short_id(container.id),
                "mode": "full",
                "tail": None,
                "truncated": truncated,
                "empty": not text.strip(),
                "line_count": line_count if text else 0,
                "logs": text,
                "note": (
                    f"Output truncated to the last {MAX_FULL_LOG_CHARS} characters."
                    if truncated
                    else "Retrieved all logs currently available from Docker."
                ),
            }

        effective_tail = DEFAULT_LOG_TAIL if tail is None else max(0, int(tail))
        raw = container.logs(
            stdout=True,
            stderr=True,
            timestamps=False,
            tail=effective_tail,
        )
        text = raw.decode("utf-8", errors="replace")
        return {
            "container": name,
            "id": _short_id(container.id),
            "mode": "tail",
            "tail": effective_tail,
            "truncated": False,
            "empty": not text.strip(),
            "line_count": (
                text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            )
            if text
            else 0,
            "logs": text,
            "note": f"Showing the last {effective_tail} lines.",
        }
    except NotFound as exc:
        raise ContainerNotFoundError(f"No container matched '{target}'.") from exc
    except APIError as exc:
        raise DockerUnavailableError(f"Failed to read logs: {exc}") from exc


def search_containers(
    client: docker.DockerClient,
    keyword: str,
    *,
    running_only: bool = False,
    status: str | None = None,
) -> dict[str, Any]:
    """Case-insensitive name keyword search."""
    if not keyword.strip():
        raise ValueError("Search keyword must not be empty.")

    all_containers = not running_only
    if status and status != "running":
        all_containers = True
        running_only = False
    scope = status or ("running" if running_only else "all")
    containers = list_containers(
        client, all_containers=all_containers, status=status
    )
    needle = keyword.lower()
    matches = [c for c in containers if needle in c["name"].lower()]
    return {
        "keyword": keyword,
        "scope": scope,
        "count": len(matches),
        "matches": matches,
    }


def restarting_containers(
    client: docker.DockerClient,
) -> list[dict[str, Any]]:
    """Containers currently restarting or with a non-zero restart count."""
    containers = list_containers(client, all_containers=True)
    return [
        c
        for c in containers
        if c.get("restarting") or c.get("restarts", 0) > 0 or c["status"] == "restarting"
    ]
