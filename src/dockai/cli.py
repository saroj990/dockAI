"""Typer CLI for Phase 1 read-only Docker operations."""

from __future__ import annotations

from typing import Optional

import typer

from dockai import __version__
from dockai.docker_client import get_client
from dockai.errors import AmbiguousContainerError, DockaiError
from dockai.formatting import (
    print_containers,
    print_error,
    print_inspect,
    print_logs,
    print_search,
)
from dockai.tools import (
    get_container_logs,
    inspect_container,
    list_containers,
    search_containers,
)

app = typer.Typer(
    name="dockai",
    help="Natural-language Docker agent — Phase 1: Docker foundation (read-only).",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _handle(exc: Exception) -> None:
    if isinstance(exc, AmbiguousContainerError):
        print_error(str(exc))
        print_containers(exc.matches, title="Matches")
        raise typer.Exit(code=2) from exc
    if isinstance(exc, DockaiError):
        print_error(str(exc))
        raise typer.Exit(code=1) from exc
    if isinstance(exc, ValueError):
        print_error(str(exc))
        raise typer.Exit(code=1) from exc
    print_error(f"Unexpected error: {exc}")
    raise typer.Exit(code=1) from exc


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """dockai CLI."""


@app.command("containers")
def containers_cmd(
    all_containers: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include stopped containers.",
    ),
) -> None:
    """List containers (running by default)."""
    try:
        client = get_client()
        items = list_containers(client, all_containers=all_containers)
        title = "All containers" if all_containers else "Running containers"
        print_containers(
            items,
            columns=["id", "name", "status", "image", "uptime"],
            title=title,
            empty_message="No containers found.",
        )
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        _handle(exc)


@app.command("inspect")
def inspect_cmd(
    target: str = typer.Argument(..., help="Container name or ID."),
) -> None:
    """Inspect a container's state and useful metadata."""
    try:
        client = get_client()
        print_inspect(inspect_container(client, target))
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("logs")
def logs_cmd(
    target: str = typer.Argument(..., help="Container name or ID."),
    tail: Optional[int] = typer.Option(
        None,
        "--tail",
        "-n",
        help="Number of lines from the end. Default: 100.",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Retrieve all logs available from Docker (may truncate for safety).",
    ),
) -> None:
    """Show container logs (default: last 100 lines)."""
    try:
        if full and tail is not None:
            print_error("Use either --full or --tail, not both.")
            raise typer.Exit(code=1)
        client = get_client()
        result = get_container_logs(client, target, tail=tail, full=full)
        print_logs(result)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("search")
def search_cmd(
    keyword: str = typer.Argument(..., help="Case-insensitive name keyword."),
    running_only: bool = typer.Option(
        False,
        "--running-only",
        help="Search running containers only (default: all).",
    ),
) -> None:
    """Find containers by name keyword."""
    try:
        client = get_client()
        print_search(search_containers(client, keyword, running_only=running_only))
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("uptime")
def uptime_cmd(
    all_containers: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include stopped containers.",
    ),
) -> None:
    """Show uptime for running containers (and state for stopped ones with --all)."""
    try:
        client = get_client()
        items = list_containers(client, all_containers=all_containers)
        print_containers(
            items,
            columns=["id", "name", "status", "uptime"],
            title="Container uptime",
            empty_message="No containers found.",
        )
    except Exception as exc:  # noqa: BLE001
        _handle(exc)
