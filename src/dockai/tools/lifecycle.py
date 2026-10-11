"""Start / stop / restart with preview and post-action verification."""

from __future__ import annotations

from typing import Any, Literal

import docker
from docker.errors import APIError

from dockai.errors import DockerUnavailableError
from dockai.tools.containers import inspect_container, resolve_container, summarize_container

Action = Literal["start", "stop", "restart"]

_IMPACT = {
    "start": "Start the container if it is stopped. Running processes inside will begin.",
    "stop": "Stop the container. Connected clients will lose service until it is started again.",
    "restart": "Restart the container. There will be a brief interruption of service.",
}


def propose_action(
    client: docker.DockerClient,
    action: Action,
    target: str,
) -> dict[str, Any]:
    """Resolve target and describe impact. Does not change Docker state."""
    if action not in _IMPACT:
        raise ValueError(f"Unsupported action '{action}'. Use start, stop, or restart.")
    summary = inspect_container(client, target)
    return {
        "needs_confirmation": True,
        "action": action,
        "target": summary["name"],
        "container": {
            "id": summary["id"],
            "name": summary["name"],
            "status": summary["status"],
            "image": summary["image"],
        },
        "impact": _IMPACT[action],
        "message": (
            f"Proposed {action} of '{summary['name']}' "
            f"({summary['id']}), currently {summary['status']}."
        ),
    }


def apply_action(
    client: docker.DockerClient,
    action: Action,
    target: str,
) -> dict[str, Any]:
    """Execute start/stop/restart, then report observed Docker state."""
    if action not in _IMPACT:
        raise ValueError(f"Unsupported action '{action}'. Use start, stop, or restart.")

    before = inspect_container(client, target)
    container = resolve_container(client, target)
    try:
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop()
        else:
            container.restart()
        container.reload()
    except APIError as exc:
        raise DockerUnavailableError(
            f"Failed to {action} '{before['name']}': {exc}"
        ) from exc

    after = summarize_container(container)
    return {
        "needs_confirmation": False,
        "action": action,
        "target": after["name"],
        "before": {
            "id": before["id"],
            "name": before["name"],
            "status": before["status"],
        },
        "after": {
            "id": after["id"],
            "name": after["name"],
            "status": after["status"],
        },
        "message": (
            f"{action.capitalize()} of '{after['name']}' finished. "
            f"Status was {before['status']}, now {after['status']}."
        ),
    }
