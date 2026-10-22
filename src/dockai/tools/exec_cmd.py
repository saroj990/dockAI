"""Container exec with propose → user confirm → apply (LLM cannot bypass)."""

from __future__ import annotations

from typing import Any

import docker
from docker.errors import APIError

from dockai.errors import DockerUnavailableError
from dockai.tools.containers import inspect_container, resolve_container

# Soft refusals for clearly destructive one-liners (confirm still required for the rest).
_BLOCKED = (
    "rm -rf /",
    "mkfs",
    ":(){",
    "dd if=/dev/zero",
)


def propose_exec(
    client: docker.DockerClient,
    target: str,
    command: str,
) -> dict[str, Any]:
    """Resolve target and describe the exec. Does not run anything."""
    cmd = (command or "").strip()
    if not cmd:
        raise ValueError("Exec command must not be empty.")
    lowered = cmd.lower()
    for bad in _BLOCKED:
        if bad in lowered:
            raise ValueError(
                f"Refused to propose exec: command looks destructive ({bad!r})."
            )
    summary = inspect_container(client, target)
    return {
        "needs_confirmation": True,
        "action": "exec",
        "target": summary["name"],
        "command": cmd,
        "container": {
            "id": summary["id"],
            "name": summary["name"],
            "status": summary["status"],
            "image": summary["image"],
        },
        "impact": (
            f"Run `{cmd}` inside '{summary['name']}' via docker exec. "
            "This can change files or processes inside the container."
        ),
        "message": (
            f"Proposed exec in '{summary['name']}' ({summary['id']}): {cmd}"
        ),
    }


def apply_exec(
    client: docker.DockerClient,
    target: str,
    command: str,
) -> dict[str, Any]:
    """Run the confirmed command inside the container and return observed output."""
    cmd = (command or "").strip()
    if not cmd:
        raise ValueError("Exec command must not be empty.")
    before = inspect_container(client, target)
    container = resolve_container(client, target)
    try:
        exit_code, output = container.exec_run(cmd, demux=False)
    except APIError as exc:
        raise DockerUnavailableError(
            f"Failed to exec in '{before['name']}': {exc}"
        ) from exc

    if isinstance(output, (bytes, bytearray)):
        text = output.decode("utf-8", errors="replace")
    else:
        text = str(output or "")
    # Cap output so terminals / LLM context stay usable.
    max_chars = 20_000
    truncated = len(text) > max_chars
    if truncated:
        text = text[-max_chars:]

    return {
        "needs_confirmation": False,
        "action": "exec",
        "target": before["name"],
        "command": cmd,
        "exit_code": int(exit_code) if exit_code is not None else None,
        "output": text,
        "truncated": truncated,
        "message": (
            f"Exec in '{before['name']}' finished with exit code {exit_code}."
        ),
    }
