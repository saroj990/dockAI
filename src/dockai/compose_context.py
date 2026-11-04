"""Discover Compose projects in cwd and report service runtime status."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docker
from docker.models.containers import Container

from dockai.errors import DockaiError

COMPOSE_FILENAMES: tuple[str, ...] = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)

ServiceState = Literal["running", "stopped", "missing"]


class ComposeContextError(DockaiError):
    """Compose file or project could not be loaded."""


@dataclass(frozen=True)
class ComposeServiceStatus:
    name: str
    state: ServiceState
    container_name: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class ComposeProjectStatus:
    compose_file: Path
    project_name: str
    services: tuple[ComposeServiceStatus, ...]

    @property
    def running_count(self) -> int:
        return sum(1 for s in self.services if s.state == "running")

    @property
    def total_count(self) -> int:
        return len(self.services)

    def stopped_or_missing(self) -> list[ComposeServiceStatus]:
        return [s for s in self.services if s.state != "running"]


def find_compose_file(directory: Path | None = None) -> Path | None:
    """Return a Compose file in `directory` (default: cwd), or None."""
    base = (directory or Path.cwd()).resolve()
    for name in COMPOSE_FILENAMES:
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def infer_project_name(compose_file: Path, content: str) -> str:
    match = re.search(r"^name:\s*['\"]?([a-zA-Z0-9_.-]+)", content, re.MULTILINE)
    if match:
        return match.group(1)
    slug = compose_file.parent.name.lower()
    return re.sub(r"[^a-z0-9-]+", "-", slug).strip("-") or "default"


def parse_compose_service_names(content: str) -> list[str]:
    """
    Parse top-level service names from a Compose file (stdlib only).

    Reads the `services:` block; ignores nested keys.
    """
    lines = content.splitlines()
    in_services = False
    services: list[str] = []
    service_key = re.compile(r"^  ([a-zA-Z0-9_.-]+):\s*(?:#.*)?$")

    for line in lines:
        if not in_services:
            if re.match(r"^services:\s*(#.*)?$", line):
                in_services = True
            continue
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            match = service_key.match(line)
            if match and match.group(1) not in {"extends", "profiles"}:
                services.append(match.group(1))
    return services


def _compose_labels(container: Container) -> tuple[str | None, str | None]:
    config = container.attrs.get("Config") or {}
    labels = config.get("Labels") or container.attrs.get("Labels") or {}
    project = labels.get("com.docker.compose.project")
    service = labels.get("com.docker.compose.service")
    return (
        str(project) if project else None,
        str(service) if service else None,
    )


def _primary_name(container: Container) -> str:
    names = container.attrs.get("Names") or container.name
    if isinstance(names, list) and names:
        return str(names[0]).lstrip("/")
    if container.name:
        return container.name.lstrip("/")
    return container.id[:12]


def _runtime_state(container: Container) -> ServiceState:
    state = container.attrs.get("State")
    if isinstance(state, dict):
        status = (state.get("Status") or "").lower()
    elif isinstance(state, str):
        status = state.lower()
    else:
        status = (container.status or "").lower()
    if status == "running":
        return "running"
    return "stopped"


def build_compose_project_status(
    client: docker.DockerClient,
    compose_file: Path,
) -> ComposeProjectStatus:
    content = compose_file.read_text(encoding="utf-8")
    project_name = infer_project_name(compose_file, content)
    declared = parse_compose_service_names(content)
    if not declared:
        raise ComposeContextError(
            f"No services found in {compose_file.name}. "
            "Add a `services:` section or check the file path."
        )

    by_service: dict[str, list[Container]] = {name: [] for name in declared}
    try:
        containers = client.containers.list(all=True)
    except Exception as exc:
        raise ComposeContextError(f"Failed to list containers: {exc}") from exc

    for container in containers:
        project, service = _compose_labels(container)
        if project != project_name or not service:
            continue
        if service in by_service:
            by_service[service].append(container)

    statuses: list[ComposeServiceStatus] = []
    for name in declared:
        matches = by_service.get(name) or []
        if not matches:
            statuses.append(ComposeServiceStatus(name=name, state="missing"))
            continue
        running = [c for c in matches if _runtime_state(c) == "running"]
        if running:
            chosen = running[0]
            statuses.append(
                ComposeServiceStatus(
                    name=name,
                    state="running",
                    container_name=_primary_name(chosen),
                    status=chosen.status,
                )
            )
        else:
            chosen = matches[0]
            statuses.append(
                ComposeServiceStatus(
                    name=name,
                    state="stopped",
                    container_name=_primary_name(chosen),
                    status=chosen.status,
                )
            )

    return ComposeProjectStatus(
        compose_file=compose_file.resolve(),
        project_name=project_name,
        services=tuple(statuses),
    )


def compose_up(
    compose_file: Path,
    *,
    services: list[str] | None = None,
) -> None:
    """Run `docker compose up -d` for all or selected services."""
    workdir = compose_file.parent
    cmd = ["docker", "compose", "-f", str(compose_file.name), "up", "-d"]
    if services:
        cmd.extend(services)
    try:
        subprocess.run(
            cmd,
            cwd=str(workdir),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ComposeContextError(
            "docker CLI not found. Install Docker and the Compose plugin."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ComposeContextError(
            f"`docker compose up -d` failed: {detail or exc}"
        ) from exc
