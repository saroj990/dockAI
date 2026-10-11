"""Typer CLI — Phase 1 tools + Phase 2 natural-language ask."""

from __future__ import annotations

import sys
import time
from typing import Optional

import typer

from dockai import __version__
from dockai.agent import ChatSession, run_agent
from dockai.docker_client import get_client
from dockai.errors import AmbiguousContainerError, DockaiError
from dockai.formatting import (
    busy_status,
    console,
    print_containers,
    print_elapsed,
    print_error,
    print_inspect,
    print_logs,
    print_search,
)
from dockai.llm.ollama import OllamaProvider
from dockai.tools import (
    get_container_logs,
    inspect_container,
    list_containers,
    search_containers,
)

app = typer.Typer(
    name="dockai",
    help="Natural-language Docker agent.",
    no_args_is_help=True,
)

_SUBCOMMANDS = frozenset(
    {"ask", "chat", "containers", "inspect", "logs", "search", "uptime"}
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


def _run_ask(prompt: str, *, model: str | None = None) -> None:
    llm = OllamaProvider(model=model)
    try:
        started = time.perf_counter()
        with busy_status("Working on it — fetching results, please wait…") as status:
            client = get_client()
            result = run_agent(
                prompt,
                llm=llm,
                client=client,
                on_progress=lambda msg: status.update(f"[cyan]{msg}[/cyan]"),
            )
        console.print(result.answer)
        print_elapsed(time.perf_counter() - started)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)
    finally:
        llm.close()


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


@app.command("ask")
def ask_cmd(
    prompt: str = typer.Argument(..., help="Natural-language Docker request."),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Ollama model name (default: DOCKAI_MODEL or llama3.1:8b).",
    ),
) -> None:
    """Ask in natural language via Ollama tool calling."""
    _run_ask(prompt, model=model)


@app.command("chat")
def chat_cmd(
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Ollama model name (default: DOCKAI_MODEL or llama3.1:8b).",
    ),
) -> None:
    """Interactive chat with follow-ups in one session."""
    llm = OllamaProvider(model=model)
    try:
        client = get_client()
        session = ChatSession(llm=llm, client=client)
        console.print(
            "[bold]dockai chat[/bold] — follow-ups stay in this session. "
            "Type [cyan]exit[/cyan] to quit."
        )
        while True:
            try:
                line = typer.prompt("You")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in {"exit", "quit", "q"}:
                break
            try:
                started = time.perf_counter()
                with busy_status(
                    "Working on it — fetching results, please wait…"
                ) as status:
                    result = session.ask(
                        text,
                        on_progress=lambda msg: status.update(f"[cyan]{msg}[/cyan]"),
                    )
                console.print(f"[bold]Agent:[/bold] {result.answer}")
                print_elapsed(time.perf_counter() - started)
                if session.focus_container:
                    console.print(
                        f"[dim]Focused: {session.focus_container}[/dim]"
                    )
            except DockaiError as exc:
                print_error(str(exc))
            except Exception as exc:  # noqa: BLE001
                _handle(exc)
    finally:
        llm.close()


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
    except Exception as exc:  # noqa: BLE001
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


def main_cli() -> None:
    """Entry point: bare prompts become `ask` without breaking subcommands."""
    args = sys.argv[1:]
    if args:
        first = args[0]
        if first not in _SUBCOMMANDS and not first.startswith("-"):
            sys.argv.insert(1, "ask")
    app()
