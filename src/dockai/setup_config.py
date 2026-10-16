"""Interactive Ollama host/model setup (`dockai setup config`)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dockai.config import config_path_for_write, normalize_ollama_host, save_ollama_config
from dockai.errors import DockaiError
from dockai.llm.ollama import OllamaNotFoundError, list_ollama_models


class SetupConfigError(DockaiError):
    """Setup could not complete."""


def run_setup_config(
    *,
    config_path: Path | None = None,
    prompt_url: Callable[[], str],
    prompt_model_index: Callable[[list[str]], int],
    list_models: Callable[[str], list[str]] | None = None,
) -> Path:
    """
    Prompt for Ollama URL and model, then persist [ollama] host/model to TOML.

    Returns the config file path written.
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
            f"No models are available on {host}. Pull a model with Ollama first."
        )

    index = prompt_model_index(models)
    if index < 1 or index > len(models):
        raise SetupConfigError(f"Choose a number between 1 and {len(models)}.")

    model = models[index - 1]
    save_ollama_config(path, host=host, model=model)
    return path
