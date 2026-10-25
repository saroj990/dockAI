"""Docker Engine client factory."""

from __future__ import annotations

import docker
from docker.errors import DockerException

from dockai.config import Settings, load_settings
from dockai.diagnostics import LOGGER
from dockai.errors import DockerUnavailableError


def _docker_unavailable_error(exc: DockerException) -> DockerUnavailableError:
    text = str(exc).lower()
    if "connection refused" in text or "connection aborted" in text:
        return DockerUnavailableError("Docker is not running.", kind="connection_refused")
    if "permission denied" in text:
        return DockerUnavailableError(
            "Could not connect to Docker (permission denied).",
            kind="permission_denied",
        )
    return DockerUnavailableError(
        "Docker Engine is unavailable. Is Docker running, and do you have permission?",
        kind="unavailable",
    )


def get_client(settings: Settings | None = None) -> docker.DockerClient:
    """Return a Docker client or raise a clear domain error."""
    cfg = settings or load_settings()
    timeout = cfg.docker_timeout
    try:
        LOGGER.debug("Connecting to Docker (timeout=%ss)", timeout)
        client = docker.from_env(timeout=timeout)
        client.ping()
        return client
    except DockerException as exc:
        LOGGER.debug("Docker unavailable: %s", exc)
        raise _docker_unavailable_error(exc) from exc
