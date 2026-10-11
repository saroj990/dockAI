"""Typer CLI — read tools, NL ask/chat, and confirmed lifecycle ops."""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from typing import Any, Optional

import typer

from dockai import __version__
from dockai.agent import ChatSession, run_agent
from dockai.config import Settings, load_settings
from dockai.diagnostics import configure_diagnostics
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
    apply_action,
    get_container_logs,
    inspect_container,
    list_containers,
    propose_action,
    search_containers,
)
from dockai.tools.lifecycle import Action

app = typer.Typer(
    name="dockai",
    help="Natural-language Docker agent.",
    no_args_is_help=True,
)

_SUBCOMMANDS = frozenset(
    {
        "ask",
        "chat",
        "config",
        "containers",
        "inspect",
        "logs",
        "search",
        "uptime",
        "start",
        "stop",
        "restart",
    }
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


def _print_pending(pending: dict[str, Any]) -> None:
    container = pending.get("container") or {}
    console.print(pending.get("message", "Confirmation required."))
    console.print(f"[bold]Impact:[/bold] {pending.get('impact', '')}")
    console.print(
        f"[bold]Target:[/bold] {container.get('name')} "
        f"({container.get('id')}) — status: {container.get('status')}"
    )


def _confirm_and_apply(client: Any, pending: dict[str, Any]) -> None:
    """Ask the user, then apply in-app (LLM cannot bypass this)."""
    _print_pending(pending)
    if not typer.confirm("Proceed with this change?", default=False):
        console.print("[yellow]Cancelled — no changes made.[/yellow]")
        return
    action: Action = pending["action"]
    target = pending["target"]
    with busy_status(f"Applying {action} — please wait…"):
        outcome = apply_action(client, action, target)
    console.print(f"[green]{outcome['message']}[/green]")


def _ctx_settings(ctx: typer.Context) -> Settings:
    return ctx.ensure_object(dict).setdefault("settings", load_settings())


def _run_ask(
    prompt: str,
    *,
    settings: Settings,
    model: str | None = None,
) -> None:
    cfg = replace(settings, ollama_model=model or settings.ollama_model)
    llm = OllamaProvider(settings=cfg, model=model)
    try:
        started = time.perf_counter()
        with busy_status("Working on it — fetching results, please wait…") as status:
            client = get_client(settings=cfg)
            result = run_agent(
                prompt,
                llm=llm,
                client=client,
                on_progress=lambda msg: status.update(f"[cyan]{msg}[/cyan]"),
            )
        console.print(result.answer)
        print_elapsed(time.perf_counter() - started)
        if result.pending_action:
            _confirm_and_apply(client, result.pending_action)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)
    finally:
        llm.close()


def _lifecycle_cmd(
    action: Action,
    target: str,
    *,
    settings: Settings,
) -> None:
    try:
        started = time.perf_counter()
        client = get_client(settings=settings)
        pending = propose_action(client, action, target)
        _confirm_and_apply(client, pending)
        print_elapsed(time.perf_counter() - started)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable diagnostic logs (tool calls/errors). Same as DOCKAI_DEBUG=1.",
    ),
    config: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to dockai.toml (default: ./dockai.toml or ~/.config/dockai/config.toml).",
    ),
) -> None:
    """dockai CLI."""
    ctx.ensure_object(dict)
    try:
        settings = load_settings(config_path=config)
    except FileNotFoundError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc
    if verbose:
        settings = replace(settings, verbose=True)
    configure_diagnostics(verbose=settings.verbose)
    ctx.obj["settings"] = settings


@app.command("config")
def config_cmd(ctx: typer.Context) -> None:
    """Show the resolved configuration (file, env, and defaults)."""
    settings = _ctx_settings(ctx)
    source = str(settings.config_path) if settings.config_path else "(none — using defaults/env)"
    console.print(f"[bold]Config file:[/bold] {source}")
    console.print(f"[bold]ollama.host:[/bold] {settings.ollama_host}")
    console.print(f"[bold]ollama.model:[/bold] {settings.ollama_model}")
    console.print(f"[bold]ollama.timeout:[/bold] {settings.ollama_timeout}")
    console.print(f"[bold]docker.timeout:[/bold] {settings.docker_timeout}")
    console.print(f"[bold]diagnostics.verbose:[/bold] {settings.verbose}")


@app.command("ask")
def ask_cmd(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Natural-language Docker request."),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Ollama model name (overrides config / DOCKAI_MODEL).",
    ),
) -> None:
    """Ask in natural language via Ollama tool calling."""
    _run_ask(prompt, settings=_ctx_settings(ctx), model=model)


@app.command("chat")
def chat_cmd(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Ollama model name (overrides config / DOCKAI_MODEL).",
    ),
) -> None:
    """Interactive chat with follow-ups in one session."""
    settings = _ctx_settings(ctx)
    cfg = replace(settings, ollama_model=model or settings.ollama_model)
    llm = OllamaProvider(settings=cfg, model=model)
    try:
        client = get_client(settings=cfg)
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
                if result.pending_action:
                    _confirm_and_apply(client, result.pending_action)
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
    ctx: typer.Context,
    all_containers: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include stopped containers.",
    ),
) -> None:
    """List containers (running by default)."""
    try:
        client = get_client(settings=_ctx_settings(ctx))
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
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Container name or ID."),
) -> None:
    """Inspect a container's state and useful metadata."""
    try:
        client = get_client(settings=_ctx_settings(ctx))
        print_inspect(inspect_container(client, target))
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("logs")
def logs_cmd(
    ctx: typer.Context,
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
        client = get_client(settings=_ctx_settings(ctx))
        result = get_container_logs(client, target, tail=tail, full=full)
        print_logs(result)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("search")
def search_cmd(
    ctx: typer.Context,
    keyword: str = typer.Argument(..., help="Case-insensitive name keyword."),
    running_only: bool = typer.Option(
        False,
        "--running-only",
        help="Search running containers only (default: all).",
    ),
) -> None:
    """Find containers by name keyword."""
    try:
        client = get_client(settings=_ctx_settings(ctx))
        print_search(search_containers(client, keyword, running_only=running_only))
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("uptime")
def uptime_cmd(
    ctx: typer.Context,
    all_containers: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include stopped containers.",
    ),
) -> None:
    """Show uptime for running containers (and state for stopped ones with --all)."""
    try:
        client = get_client(settings=_ctx_settings(ctx))
        items = list_containers(client, all_containers=all_containers)
        print_containers(
            items,
            columns=["id", "name", "status", "uptime"],
            title="Container uptime",
            empty_message="No containers found.",
        )
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@app.command("start")
def start_cmd(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Container name or ID."),
) -> None:
    """Start a container after explicit confirmation."""
    _lifecycle_cmd("start", target, settings=_ctx_settings(ctx))


@app.command("stop")
def stop_cmd(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Container name or ID."),
) -> None:
    """Stop a container after explicit confirmation."""
    _lifecycle_cmd("stop", target, settings=_ctx_settings(ctx))


@app.command("restart")
def restart_cmd(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Container name or ID."),
) -> None:
    """Restart a container after explicit confirmation."""
    _lifecycle_cmd("restart", target, settings=_ctx_settings(ctx))


def main_cli() -> None:
    """Entry point: bare prompts become `ask` without breaking subcommands."""
    args = sys.argv[1:]
    if args:
        first = args[0]
        if first not in _SUBCOMMANDS and not first.startswith("-"):
            sys.argv.insert(1, "ask")
    app()
