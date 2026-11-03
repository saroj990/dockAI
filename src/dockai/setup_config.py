"""Interactive Ollama host/model setup (`dockai setup config`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dockai.config import config_path_for_write, normalize_ollama_host, save_ollama_config
from dockai.errors import DockaiError
from dockai.llm.ollama import OllamaNotFoundError, list_ollama_models
from dockai.llm.resolve_host import _model_in_list


class SetupConfigError(DockaiError):
    """Setup could not complete."""


@dataclass(frozen=True)
class SetupConfigResult:
    """Outcome of a successful interactive setup (config is saved)."""

    path: Path
    host: str
    model: str
    warnings: tuple[str, ...] = ()


def _verify_model_listed(
    host: str,
    model: str,
    fetch: Callable[[str], list[str]],
) -> tuple[str, ...]:
    """
    Re-list models after save. Warn (do not fail) when the saved tag disappeared.

    Setup still saves the user's choice; they may need `ollama pull` on that host.
    """
    try:
        names = fetch(host)
    except OllamaNotFoundError:
        return (
            f"Could not re-check models on {host}. "
            f"Run `dockai doctor` or `ollama pull {model}` if chat fails.",
        )
    if _model_in_list(model, names):
        return ()
    return (
        f"Model `{model}` is not listed on {host}. "
        f"Run `ollama pull {model}` on that host, then `dockai doctor`.",
    )


def run_setup_config(
    *,
    config_path: Path | None = None,
    prompt_url: Callable[[], str],
    prompt_model_index: Callable[[list[str]], int],
    list_models: Callable[[str], list[str]] | None = None,
) -> SetupConfigResult:
    """
    Prompt for Ollama URL and model, then persist [ollama] host/model to TOML.

    Returns paths and any post-save warnings (config is written even when warned).
    """
    fetch = list_models or list_ollama_models
    path = config_path or config_path_for_write()

    try:
        host = normalize_ollama_host(prompt_url(), require_ip=True)
    except ValueError as exc:
        raise SetupConfigError(str(exc)) from exc

    try:
        models = fetch(host)
    except OllamaNotFoundError as exc:
        raise SetupConfigError(str(exc)) from exc

    if not models:
        raise SetupConfigError(
            f"No models are available on {host}. Pull a model with Ollama first "
            "(for example, `ollama pull qwen2.5:3b`), then run `dockai setup config` again."
        )

    index = prompt_model_index(models)
    if index < 1 or index > len(models):
        raise SetupConfigError(f"Choose a number between 1 and {len(models)}.")

    model = models[index - 1]
    save_ollama_config(path, host=host, model=model)
    warnings = _verify_model_listed(host, model, fetch)
    return SetupConfigResult(path=path, host=host, model=model, warnings=warnings)
