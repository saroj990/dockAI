"""Typer CLI — read tools, NL ask/chat, and confirmed lifecycle ops."""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import typer

from dockai import __version__
from dockai.compose_context import (
    ComposeContextError,
    ComposeProjectStatus,
    build_compose_project_status,
    compose_chat_context,
    compose_up,
    find_compose_file,
)
from dockai.llm.base import ChatMessage
from dockai.agent import ChatSession, run_agent
from dockai.config import Settings, config_path_for_write, load_settings
from dockai.setup_config import SetupConfigError, run_setup_config
from dockai.diagnostics import configure_diagnostics
from dockai.doctor import run_doctor
from dockai.docker_client import get_client
from dockai.errors import AmbiguousContainerError, DockaiError, DockerUnavailableError
from dockai.formatting import (
    busy_status,
    console,
    print_chat_welcome_hints,
    print_containers,
    print_docker_not_running,
    print_elapsed,
    print_error,
    print_inspect,
    print_logs,
    print_compose_status,
    print_ollama_unavailable_guidance,
    print_search,
)
from dockai.llm.docker_only import DockerOnlyLLM
from dockai.llm.ollama import OllamaNotFoundError, OllamaProvider
from dockai.llm.resolve_host import is_loopback_ollama_host, settings_with_resolved_ollama
from dockai.present import render_presentation
from dockai.prompts import prompt_numbered_model_choice
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
        "compose",
        "config",
        "containers",
        "doctor",
        "inspect",
        "logs",
        "search",
        "setup",
        "uptime",
        "start",
        "stop",
        "restart",
    }
)

setup_app = typer.Typer(
    name="setup",
    help="Interactive setup (Ollama host and model).",
    no_args_is_help=True,
)
app.add_typer(setup_app, name="setup")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _handle(exc: Exception, *, user_prompt: str | None = None) -> None:
    if isinstance(exc, AmbiguousContainerError):
        print_error(str(exc))
        print_containers(exc.matches, title="Matches")
        raise typer.Exit(code=2) from exc
    if isinstance(exc, DockerUnavailableError):
        if exc.kind == "connection_refused":
            print_docker_not_running()
        elif exc.kind == "permission_denied":
            print_docker_not_running(permission_hint=True)
        else:
            print_error(str(exc))
        raise typer.Exit(code=1) from exc
    if isinstance(exc, OllamaNotFoundError):
        print_error(str(exc))
        print_ollama_unavailable_guidance(user_prompt=user_prompt)
        raise typer.Exit(code=1) from exc
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
    if pending.get("action") == "exec" and pending.get("command"):
        console.print(f"[bold]Command:[/bold] {pending['command']}")


def _confirm_and_apply(client: Any, pending: dict[str, Any]) -> None:
    """Ask the user, then apply in-app (LLM cannot bypass this)."""
    from dockai.tools.exec_cmd import apply_exec

    _print_pending(pending)
    action = pending.get("action")
    prompt = (
        "Run this docker exec command?"
        if action == "exec"
        else "Proceed with this change?"
    )
    if not typer.confirm(prompt, default=False):
        console.print("[yellow]Cancelled — no changes made.[/yellow]")
        return
    target = pending["target"]
    with busy_status(f"Applying {action} — please wait…"):
        if action == "exec":
            outcome = apply_exec(client, target, pending["command"])
            console.print(f"[green]{outcome['message']}[/green]")
            output = outcome.get("output") or ""
            if output.strip():
                console.print(output.rstrip())
            elif outcome.get("truncated"):
                console.print("[dim](output truncated)[/dim]")
            return
        outcome = apply_action(client, action, target)
    console.print(f"[green]{outcome['message']}[/green]")


def _ctx_settings(ctx: typer.Context) -> Settings:
    return ctx.ensure_object(dict).setdefault("settings", load_settings())


def _compose_rows(status: ComposeProjectStatus) -> list[dict[str, str]]:
    return [
        {
            "service": s.name,
            "state": s.state,
            "container": s.container_name or "",
            "status": s.status or "",
        }
        for s in status.services
    ]


def _offer_compose_start(status: ComposeProjectStatus, compose_file: Path) -> None:
    stopped = status.stopped_or_missing()
    if not stopped:
        console.print("[green]All compose services are running.[/green]")
        return
    names = ", ".join(s.name for s in stopped)
    console.print(f"[yellow]Not running:[/yellow] {names}")
    choice = typer.prompt(
        "Start stopped services? [A] all  [B] choose one  [N] no",
        default="N",
    ).strip().upper()
    if choice in {"", "N"}:
        console.print("[dim]No services started.[/dim]")
        return
    try:
        if choice == "A":
            with busy_status("Starting compose services…"):
                compose_up(compose_file, services=[s.name for s in stopped])
            console.print("[green]Compose services started.[/green]")
            return
        if choice == "B":
            console.print("[bold]Stopped or missing services:[/bold]")
            for idx, svc in enumerate(stopped, start=1):
                console.print(f"  {idx}. {svc.name} ({svc.state})")
            pick = typer.prompt("Service number", type=int)
            if pick < 1 or pick > len(stopped):
                raise ComposeContextError(
                    f"Choose a number between 1 and {len(stopped)}."
                )
            target = stopped[pick - 1].name
            with busy_status(f"Starting `{target}`…"):
                compose_up(compose_file, services=[target])
            console.print(f"[green]Started `{target}`.[/green]")
            return
        raise ComposeContextError("Enter A, B, or N.")
    except ComposeContextError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc


def _run_compose_here(
    ctx: typer.Context,
    directory: Path,
    *,
    model: str | None = None,
) -> None:
    compose_file = find_compose_file(directory)
    if compose_file is None:
        print_error(
            f"No Compose file in {directory.resolve()}. "
            "Expected one of: compose.yaml, compose.yml, docker-compose.yaml, "
            "docker-compose.yml."
        )
        raise typer.Exit(code=1)
    settings = _ctx_settings(ctx)
    try:
        client = get_client(settings=settings)
        status = build_compose_project_status(client, compose_file)
    except DockerUnavailableError as exc:
        _handle(exc)
        return
    except ComposeContextError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    ctx.ensure_object(dict)["compose_project"] = status
    print_compose_status(
        compose_file=str(status.compose_file),
        project_name=status.project_name,
        running_count=status.running_count,
        total_count=status.total_count,
        rows=_compose_rows(status),
    )
    _offer_compose_start(status, compose_file)
    try:
        status = build_compose_project_status(client, compose_file)
        ctx.ensure_object(dict)["compose_project"] = status
    except ComposeContextError:
        pass
    _run_interactive_chat(
        settings,
        model=model,
        compose_status=status,
        docker_only_if_ollama_down=True,
    )


_CHAT_EXIT_WORDS = frozenset(
    {
        "exit",
        "quit",
        "q",
        "bye",
        "goodbye",
        "good bye",
        "see you",
        "see ya",
    }
)


def is_chat_exit_request(text: str) -> bool:
    """True when the user is trying to leave interactive chat."""
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return False
    if normalized in _CHAT_EXIT_WORDS:
        return True
    return normalized.startswith("bye ") or normalized.startswith("goodbye ")


def _confirm_leave_chat(*, reason: str = "Leave chat?") -> bool:
    return typer.confirm(reason, default=False)


def _run_interactive_chat(
    settings: Settings,
    *,
    model: str | None = None,
    compose_status: ComposeProjectStatus | None = None,
    docker_only_if_ollama_down: bool = False,
) -> None:
    """Interactive session until the user confirms exit."""
    docker_only_mode = False
    cfg = replace(settings, ollama_model=model or settings.ollama_model)
    try:
        cfg = _prepare_ollama_settings(settings, model=model)
    except OllamaNotFoundError as exc:
        if docker_only_if_ollama_down:
            print_error(str(exc))
            print_ollama_unavailable_guidance(user_prompt=None)
            docker_only_mode = True
        else:
            _handle(exc)
            return

    llm: OllamaProvider | DockerOnlyLLM
    if docker_only_mode:
        llm = DockerOnlyLLM()
    else:
        llm = OllamaProvider(settings=cfg, model=model)
    try:
        try:
            client = get_client(settings=cfg)
        except DockerUnavailableError as exc:
            _handle(exc)
            return
        session = ChatSession(llm=llm, client=client)
        if compose_status is not None:
            session.messages.append(
                ChatMessage(role="system", content=compose_chat_context(compose_status))
            )
        if compose_status is not None:
            console.print(
                "[bold]dockai chat[/bold] — scoped to Compose project "
                f"[cyan]{compose_status.project_name}[/cyan]. "
                "Say [cyan]exit[/cyan] or [cyan]bye[/cyan] to leave (confirmation required)."
            )
        else:
            console.print(
                "[bold]dockai chat[/bold] — follow-ups stay in this session. "
                "Say [cyan]exit[/cyan] or [cyan]bye[/cyan] to quit (confirmation required)."
            )
        if docker_only_mode:
            console.print(
                "[dim]Ollama unavailable — Docker shortcuts (logs, list, inspect) "
                "still work in this session.[/dim]"
            )
        if settings.chat_hints:
            print_chat_welcome_hints()
        while True:
            try:
                line = typer.prompt("You")
            except (EOFError, KeyboardInterrupt):
                console.print()
                if _confirm_leave_chat(reason="Leave chat?"):
                    break
                continue
            text = line.strip()
            if not text:
                continue
            if is_chat_exit_request(text):
                if _confirm_leave_chat(reason="Leave chat?"):
                    break
                continue
            try:
                started = time.perf_counter()
                with busy_status(
                    "Working on it — fetching results, please wait…"
                ) as status:
                    result = session.ask(
                        text,
                        on_progress=status.update,
                    )
                _print_agent_result(result, chat=True)
                print_elapsed(time.perf_counter() - started, result.timings)
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


def _ollama_preflight_status_message(settings: Settings) -> str:
    host = settings.ollama_host.rstrip("/")
    model = settings.ollama_model
    if is_loopback_ollama_host(host):
        return f"Pinging Ollama ({model})…"
    return f"Pinging remote Ollama ({model})…"


def _prepare_ollama_settings(
    settings: Settings,
    model: str | None = None,
) -> Settings:
    """Preflight Ollama and apply local fallback when configured remote is down."""
    cfg = replace(settings, ollama_model=model or settings.ollama_model)
    try:
        with busy_status(_ollama_preflight_status_message(cfg)) as status:
            cfg, resolved = settings_with_resolved_ollama(
                cfg, on_progress=status.update
            )
    except OllamaNotFoundError:
        raise
    if resolved.fallback_notice:
        console.print(f"[dim]{resolved.fallback_notice}[/dim]")
    return cfg


def _run_ask(
    prompt: str,
    *,
    settings: Settings,
    model: str | None = None,
) -> None:
    try:
        cfg = _prepare_ollama_settings(settings, model=model)
    except OllamaNotFoundError as exc:
        _handle(exc, user_prompt=prompt)
    llm = OllamaProvider(settings=cfg, model=model)
    try:
        started = time.perf_counter()
        with busy_status("Working on it — fetching results, please wait…") as status:
            client = get_client(settings=cfg)
            result = run_agent(
                prompt,
                llm=llm,
                client=client,
                on_progress=status.update,
            )
        _print_agent_result(result)
        print_elapsed(time.perf_counter() - started, result.timings)
        if result.pending_action:
            _confirm_and_apply(client, result.pending_action)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)
    finally:
        llm.close()


def _print_agent_result(result: Any, *, chat: bool = False) -> None:
    if result.presentation is not None:
        render_presentation(result.presentation)
    answer = (result.answer or "").strip()
    if not answer:
        return
    if chat:
        console.print(f"[bold]Agent:[/bold] {answer}")
    else:
        console.print(answer)


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


@app.command("compose")
def compose_cmd(
    ctx: typer.Context,
    directory: str = typer.Argument(
        ".",
        help="Directory containing a Compose file (default: current directory).",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Ollama model name (overrides config / DOCKAI_MODEL).",
    ),
) -> None:
    """Compose status in this folder, then interactive chat for that project."""
    _run_compose_here(ctx, Path(directory), model=model)


@app.command("config")
def config_cmd(ctx: typer.Context) -> None:
    """Show the resolved configuration (file, env, and defaults)."""
    settings = _ctx_settings(ctx)
    source = str(settings.config_path) if settings.config_path else "(none — using defaults/env)"
    console.print(f"[bold]Config file:[/bold] {source}")
    console.print(f"[bold]ollama.host:[/bold] {settings.ollama_host}")
    console.print(f"[bold]ollama.model:[/bold] {settings.ollama_model}")
    console.print(f"[bold]ollama.timeout:[/bold] {settings.ollama_timeout}")
    console.print(f"[bold]ollama.health_timeout:[/bold] {settings.ollama_health_timeout}")
    fallback = settings.ollama_fallback_host or "(default local 127.0.0.1:11434 when remote fails)"
    console.print(f"[bold]ollama.fallback_host:[/bold] {fallback}")
    fb_model = settings.ollama_fallback_model or "(same as ollama.model when falling back)"
    console.print(f"[bold]ollama.fallback_model:[/bold] {fb_model}")
    console.print(f"[bold]docker.timeout:[/bold] {settings.docker_timeout}")
    console.print(f"[bold]diagnostics.verbose:[/bold] {settings.verbose}")
    console.print(f"[bold]diagnostics.chat_hints:[/bold] {settings.chat_hints}")


@app.command("doctor")
def doctor_cmd(
    ctx: typer.Context,
    require_ollama: bool = typer.Option(
        True,
        "--require-ollama/--no-require-ollama",
        help="Check Ollama reachability and the configured model (default: on).",
    ),
) -> None:
    """Check Docker and Ollama readiness before ask/chat."""
    settings = _ctx_settings(ctx)
    code = run_doctor(settings, require_ollama=require_ollama)
    raise typer.Exit(code=code)


@setup_app.command("doctor")
def setup_doctor_cmd(
    ctx: typer.Context,
    require_ollama: bool = typer.Option(
        True,
        "--require-ollama/--no-require-ollama",
        help="Check Ollama reachability and the configured model (default: on).",
    ),
) -> None:
    """Same as `dockai doctor` (readiness checks)."""
    doctor_cmd(ctx, require_ollama=require_ollama)


@setup_app.command("config")
def setup_config_cmd(ctx: typer.Context) -> None:
    """Prompt for Ollama URL and model, then save to dockai.toml."""
    settings = _ctx_settings(ctx)
    target = config_path_for_write(config_path=settings.config_path)

    def prompt_url() -> str:
        return typer.prompt(
            "Ollama host IP (port defaults to 11434, http:// optional)",
        )

    def prompt_model_index(models: list[str]) -> int:
        return prompt_numbered_model_choice(models, console=console)

    try:
        written = run_setup_config(
            config_path=target,
            prompt_url=prompt_url,
            prompt_model_index=prompt_model_index,
        )
        console.print(f"[green]Saved Ollama settings to {written}[/green]")
        console.print("\n[bold]Next steps:[/bold]")
        console.print("  1. Run `dockai doctor` to verify Docker and Ollama readiness.")
        console.print("  2. Run `dockai containers` for a Docker-only smoke test.")
        console.print("  3. Run `dockai chat` to start the natural-language assistant.")
    except SetupConfigError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc


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
    _run_interactive_chat(_ctx_settings(ctx), model=model)


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
        if first == ".":
            sys.argv[1:2] = ["compose", "."]
        elif first not in _SUBCOMMANDS and not first.startswith("-"):
            sys.argv.insert(1, "ask")
    app()
