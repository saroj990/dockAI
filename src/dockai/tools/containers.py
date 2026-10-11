"""Read-only container tools using the Docker SDK."""

from __future__ import annotations

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
) -> list[dict[str, Any]]:
    """List containers; defaults to running only."""
    try:
        containers = client.containers.list(all=all_containers)
    except APIError as exc:
        raise DockerUnavailableError(f"Failed to list containers: {exc}") from exc
    return [summarize_container(c) for c in containers]


def _match_candidates(
    client: docker.DockerClient,
    target: str,
    *,
    all_containers: bool = True,
) -> list[Container]:
    target_l = target.lower()
    try:
        containers = client.containers.list(all=all_containers)
    except APIError as exc:
        raise DockerUnavailableError(f"Failed to list containers: {exc}") from exc

    exact: list[Container] = []
    partial: list[Container] = []
    for container in containers:
        name = _primary_name(container).lower()
        cid = container.id.lower()
        short = _short_id(container.id).lower()
        if name == target_l or cid == target_l or short == target_l:
            exact.append(container)
        elif target_l in name or cid.startswith(target_l):
            partial.append(container)
    return exact or partial


def resolve_container(
    client: docker.DockerClient,
    target: str,
    *,
    all_containers: bool = True,
) -> Container:
    """Resolve a name/ID to exactly one container."""
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
) -> dict[str, Any]:
    """Case-insensitive name keyword search."""
    if not keyword.strip():
        raise ValueError("Search keyword must not be empty.")

    scope = "running" if running_only else "all"
    containers = list_containers(client, all_containers=not running_only)
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
