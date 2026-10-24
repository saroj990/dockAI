"""Resolve a reachable Ollama host (configured primary + local fallback)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable
from urllib.parse import urlparse

from dockai.config import DEFAULT_OLLAMA_HOST, Settings
from dockai.llm.ollama import OllamaNotFoundError, list_ollama_models

ProbeFn = Callable[[str, float], bool]


@dataclass(frozen=True)
class ResolvedOllamaHost:
    host: str
    configured_host: str
    used_fallback: bool
    fallback_notice: str | None = None


def is_loopback_ollama_host(host: str) -> bool:
    parsed = urlparse(host.rstrip("/"))
    name = (parsed.hostname or "").lower()
    return name in {"127.0.0.1", "localhost", "::1"}


def _default_probe(host: str, timeout: float) -> bool:
    try:
        list_ollama_models(host, timeout=timeout)
        return True
    except OllamaNotFoundError:
        return False


def _both_unreachable_message(
    *,
    configured: str,
    fallback: str,
    tried_fallback: bool,
) -> str:
    if tried_fallback:
        return (
            "Debugging and natural-language requests need a working Ollama LLM. "
            f"Neither your configured host ({configured}) nor the fallback "
            f"({fallback}) responded. Configure a local or remote Ollama in "
            "dockai.toml ([ollama] host, model), run `dockai setup config`, "
            "or check `dockai config`."
        )
    return (
        "Debugging and natural-language requests need a working Ollama LLM. "
        f"Ollama is not reachable at {configured}. Configure a local or remote "
        "Ollama in dockai.toml ([ollama] host, model), run `dockai setup config`, "
        "or check `dockai config`."
    )


def _fallback_host_for(settings: Settings) -> str:
    raw = settings.ollama_fallback_host or DEFAULT_OLLAMA_HOST
    return raw.rstrip("/")


def _model_available(host: str, model: str, *, timeout: float) -> bool:
    names = list_ollama_models(host, timeout=timeout)
    if model in names:
        return True
    prefix = f"{model}:"
    return any(n == model or n.startswith(prefix) for n in names)


def resolve_ollama_host(
    settings: Settings,
    *,
    probe: ProbeFn | None = None,
) -> ResolvedOllamaHost:
    """
    Preflight configured Ollama; try local fallback when primary is remote.

    Raises OllamaNotFoundError when no host responds or model is missing.
    """
    probe_fn = probe or _default_probe
    health_timeout = settings.ollama_health_timeout
    configured = settings.ollama_host.rstrip("/")
    model = settings.ollama_model

    if probe_fn(configured, health_timeout):
        if not _model_available(configured, model, timeout=health_timeout):
            raise OllamaNotFoundError(
                f"Model `{model}` is not available on {configured}. "
                "Run `ollama list` on that host and set `[ollama] model` in dockai.toml."
            )
        return ResolvedOllamaHost(
            host=configured,
            configured_host=configured,
            used_fallback=False,
        )

    if is_loopback_ollama_host(configured):
        raise OllamaNotFoundError(
            _both_unreachable_message(
                configured=configured,
                fallback=configured,
                tried_fallback=False,
            )
        )

    fallback = _fallback_host_for(settings)
    if fallback.rstrip("/") == configured:
        raise OllamaNotFoundError(
            _both_unreachable_message(
                configured=configured,
                fallback=fallback,
                tried_fallback=False,
            )
        )

    if not probe_fn(fallback, health_timeout):
        raise OllamaNotFoundError(
            _both_unreachable_message(
                configured=configured,
                fallback=fallback,
                tried_fallback=True,
            )
        )

    if not _model_available(fallback, model, timeout=health_timeout):
        raise OllamaNotFoundError(
            f"Fallback Ollama at {fallback} is up but model `{model}` is not pulled. "
            f"Run `ollama pull {model}` locally or change `[ollama] model` in dockai.toml."
        )

    notice = (
        f"Using Ollama at {fallback} (configured host {configured} unreachable)."
    )
    return ResolvedOllamaHost(
        host=fallback,
        configured_host=configured,
        used_fallback=True,
        fallback_notice=notice,
    )


def settings_with_resolved_ollama(
    settings: Settings,
    *,
    probe: ProbeFn | None = None,
) -> tuple[Settings, ResolvedOllamaHost]:
    """Return settings with ollama_host replaced by the resolved reachable host."""
    resolved = resolve_ollama_host(settings, probe=probe)
    updated = replace(settings, ollama_host=resolved.host)
    return updated, resolved
