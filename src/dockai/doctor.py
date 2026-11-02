"""Readiness checks for Docker and Ollama (`dockai doctor`)."""

from __future__ import annotations

from dockai.config import Settings
from dockai.docker_client import get_client
from dockai.errors import DockerUnavailableError
from dockai.formatting import console
from dockai.llm.ollama import OllamaNotFoundError
from dockai.llm.resolve_host import _fallback_model_for, resolve_ollama_host


def _docker_fix_hint(exc: DockerUnavailableError) -> str:
    if exc.kind == "permission_denied":
        return "Fix socket permissions (docker group) and confirm `docker ps` works."
    if exc.kind == "connection_refused":
        return "Start Docker Desktop or the daemon, then run `docker ps`."
    return "Confirm Docker is running and reachable, then run `docker ps`."


def _ollama_fix_hint(exc: OllamaNotFoundError, settings: Settings) -> str:
    text = str(exc)
    model = settings.ollama_model
    if "ollama pull" in text.lower() or "not available" in text.lower():
        return f"Run `ollama pull {model}` or change `[ollama] model` via `dockai setup config`."
    return (
        "Start Ollama (`ollama serve`), check `[ollama] host` in dockai.toml, "
        "or run `dockai setup config`."
    )


def run_doctor(settings: Settings, *, require_ollama: bool = True) -> int:
    """
    Run ordered readiness checks. Returns exit code 0 when required checks pass.
    """
    failed = False
    config_source = (
        str(settings.config_path) if settings.config_path else "(none — defaults / env)"
    )
    console.print(f"[green]✓[/green] Config: {config_source}")

    try:
        client = get_client(settings=settings)
        client.ping()
        console.print("[green]✓[/green] Docker: OK")
    except DockerUnavailableError as exc:
        failed = True
        console.print(f"[red]✗[/red] Docker: {exc}")
        console.print(f"[dim]  → {_docker_fix_hint(exc)}[/dim]")

    if require_ollama:
        try:
            resolved = resolve_ollama_host(settings)
            active_host = resolved.host.rstrip("/")
            active_model = (
                _fallback_model_for(settings)
                if resolved.used_fallback
                else settings.ollama_model
            )
            if resolved.used_fallback:
                console.print(
                    f"[green]✓[/green] Ollama: OK at {active_host} "
                    f"(configured {resolved.configured_host} unreachable)"
                )
            else:
                console.print(f"[green]✓[/green] Ollama: OK at {active_host}")
            console.print(f"[green]✓[/green] Model `{active_model}`: available")
        except OllamaNotFoundError as exc:
            failed = True
            console.print(f"[red]✗[/red] Ollama: {exc}")
            console.print(f"[dim]  → {_ollama_fix_hint(exc, settings)}[/dim]")
    else:
        console.print("[dim]Ollama checks skipped (--no-require-ollama).[/dim]")

    return 1 if failed else 0
