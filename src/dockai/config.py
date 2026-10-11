"""Load dockai settings from TOML config, env, and CLI overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_TIMEOUT = 120.0
DEFAULT_DOCKER_TIMEOUT = 60.0


@dataclass(frozen=True)
class Settings:
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout: float = DEFAULT_OLLAMA_TIMEOUT
    docker_timeout: float = DEFAULT_DOCKER_TIMEOUT
    verbose: bool = False
    config_path: Path | None = None


def config_search_paths() -> list[Path]:
    """Locations checked in order; first existing file wins."""
    paths: list[Path] = []
    override = os.getenv("DOCKAI_CONFIG", "").strip()
    if override:
        paths.append(Path(override).expanduser())
    paths.append(Path.cwd() / "dockai.toml")
    xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg:
        paths.append(Path(xdg).expanduser() / "dockai" / "config.toml")
    else:
        paths.append(Path.home() / ".config" / "dockai" / "config.toml")
    return paths


def find_config_file() -> Path | None:
    for path in config_search_paths():
        if path.is_file():
            return path
    return None


def _as_float(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _load_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


def load_settings(
    *,
    model: str | None = None,
    config_path: str | Path | None = None,
) -> Settings:
    """
    Resolve settings.

    Precedence: explicit CLI args > environment > config file > defaults.
    """
    path: Path | None
    if config_path is not None:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
    else:
        path = find_config_file()

    file_data: dict = _load_toml(path) if path is not None else {}
    ollama = file_data.get("ollama") if isinstance(file_data.get("ollama"), dict) else {}
    docker = file_data.get("docker") if isinstance(file_data.get("docker"), dict) else {}
    diagnostics = (
        file_data.get("diagnostics")
        if isinstance(file_data.get("diagnostics"), dict)
        else {}
    )

    host = (
        os.getenv("OLLAMA_HOST")
        or (str(ollama["host"]) if ollama.get("host") else None)
        or DEFAULT_OLLAMA_HOST
    ).rstrip("/")

    resolved_model = (
        model
        or os.getenv("DOCKAI_MODEL")
        or (str(ollama["model"]) if ollama.get("model") else None)
        or DEFAULT_OLLAMA_MODEL
    )

    if os.getenv("DOCKAI_OLLAMA_TIMEOUT"):
        ollama_timeout = _as_float(os.getenv("DOCKAI_OLLAMA_TIMEOUT"), DEFAULT_OLLAMA_TIMEOUT)
    else:
        ollama_timeout = _as_float(ollama.get("timeout"), DEFAULT_OLLAMA_TIMEOUT)

    if os.getenv("DOCKAI_DOCKER_TIMEOUT"):
        docker_timeout = _as_float(os.getenv("DOCKAI_DOCKER_TIMEOUT"), DEFAULT_DOCKER_TIMEOUT)
    else:
        docker_timeout = _as_float(docker.get("timeout"), DEFAULT_DOCKER_TIMEOUT)

    env_debug = os.getenv("DOCKAI_DEBUG")
    if env_debug is not None and env_debug.strip() != "":
        verbose = _as_bool(env_debug, False)
    else:
        verbose = _as_bool(diagnostics.get("verbose"), False)

    return Settings(
        ollama_host=host,
        ollama_model=resolved_model,
        ollama_timeout=ollama_timeout,
        docker_timeout=docker_timeout,
        verbose=verbose,
        config_path=path,
    )
