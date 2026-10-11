"""Docker Engine client factory."""

from __future__ import annotations

import os

import docker
from docker.errors import DockerException

from dockai.diagnostics import LOGGER
from dockai.errors import DockerUnavailableError


def _timeout() -> float:
    raw = os.getenv("DOCKAI_DOCKER_TIMEOUT", "60")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 60.0


def get_client() -> docker.DockerClient:
    """Return a Docker client or raise a clear domain error."""
    timeout = _timeout()
    try:
        LOGGER.debug("Connecting to Docker (timeout=%ss)", timeout)
        client = docker.from_env(timeout=timeout)
        client.ping()
        return client
    except DockerException as exc:
        LOGGER.debug("Docker unavailable: %s", exc)
        raise DockerUnavailableError(
            "Docker Engine is unavailable. Is Docker running, and do you have permission?"
        ) from exc
