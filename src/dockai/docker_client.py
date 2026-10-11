"""Docker Engine client factory."""

from __future__ import annotations

import docker
from docker.errors import DockerException

from dockai.errors import DockerUnavailableError


def get_client() -> docker.DockerClient:
    """Return a Docker client or raise a clear domain error."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        raise DockerUnavailableError(
            "Docker Engine is unavailable. Is Docker running, and do you have permission?"
        ) from exc
