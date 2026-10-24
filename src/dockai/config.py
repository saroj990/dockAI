"""Load dockai settings from TOML config, env, and CLI overrides."""

from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_OLLAMA_PORT = 11434
DEFAULT_OLLAMA_HOST = f"http://127.0.0.1:{DEFAULT_OLLAMA_PORT}"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_TIMEOUT = 120.0
DEFAULT_OLLAMA_HEALTH_TIMEOUT = 5.0
MAX_OLLAMA_HEALTH_TIMEOUT = 5.0
DEFAULT_DOCKER_TIMEOUT = 60.0


@dataclass(frozen=True)
class Settings:
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout: float = DEFAULT_OLLAMA_TIMEOUT
    ollama_health_timeout: float = DEFAULT_OLLAMA_HEALTH_TIMEOUT
    ollama_fallback_host: str | None = None
    ollama_fallback_model: str | None = None
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


def config_path_for_write(*, config_path: Path | None = None) -> Path:
    """Path to create or update when running `dockai setup config`."""
    if config_path is not None:
        return config_path
    existing = find_config_file()
    if existing is not None:
        return existing
    return Path.cwd() / "dockai.toml"


def _as_float(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return default


def _as_health_timeout(value: object) -> float:
    """Preflight ping budget (seconds); capped for fast fallback to local Ollama."""
    return min(MAX_OLLAMA_HEALTH_TIMEOUT, _as_float(value, DEFAULT_OLLAMA_HEALTH_TIMEOUT))


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


def normalize_ollama_host(raw: str, *, require_ip: bool = False) -> str:
    """
    Build a canonical Ollama base URL.

    ``http://`` is optional; port defaults to 11434. When ``require_ip`` is
    true (setup CLI), the host must be a valid IPv4/IPv6 address.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("Ollama host IP address is required.")

    if not text.startswith(("http://", "https://")):
        text = f"http://{text}"

    parsed = urlparse(text)
    if not parsed.hostname:
        raise ValueError("Ollama host IP address is required.")

    scheme = parsed.scheme or "http"
    if scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported Ollama URL scheme: {scheme!r}")

    host = parsed.hostname
    if require_ip:
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(
                f"Enter a valid IP address (got {host!r})."
            ) from exc

    port = parsed.port or DEFAULT_OLLAMA_PORT
    try:
        parsed_ip = ipaddress.ip_address(host)
        if isinstance(parsed_ip, ipaddress.IPv6Address):
            authority = f"[{host}]:{port}"
        else:
            authority = f"{host}:{port}"
    except ValueError:
        authority = f"{host}:{port}"

    return f"{scheme}://{authority}".rstrip("/")


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

    host_raw = (
        os.getenv("OLLAMA_HOST")
        or (str(ollama["host"]) if ollama.get("host") else None)
        or DEFAULT_OLLAMA_HOST
    )
    host = normalize_ollama_host(host_raw, require_ip=False)

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

    if os.getenv("DOCKAI_OLLAMA_HEALTH_TIMEOUT"):
        ollama_health_timeout = _as_health_timeout(
            os.getenv("DOCKAI_OLLAMA_HEALTH_TIMEOUT")
        )
    else:
        ollama_health_timeout = _as_health_timeout(ollama.get("health_timeout"))

    fallback_raw = os.getenv("DOCKAI_OLLAMA_FALLBACK_HOST") or ollama.get("fallback_host")
    ollama_fallback_host: str | None
    if fallback_raw:
        ollama_fallback_host = normalize_ollama_host(str(fallback_raw), require_ip=False)
    else:
        ollama_fallback_host = None

    fallback_model_raw = os.getenv("DOCKAI_OLLAMA_FALLBACK_MODEL") or ollama.get(
        "fallback_model"
    )
    ollama_fallback_model: str | None
    if fallback_model_raw:
        ollama_fallback_model = str(fallback_model_raw).strip()
    else:
        ollama_fallback_model = None

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
        ollama_health_timeout=ollama_health_timeout,
        ollama_fallback_host=ollama_fallback_host,
        ollama_fallback_model=ollama_fallback_model,
        docker_timeout=docker_timeout,
        verbose=verbose,
        config_path=path,
    )


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


def _write_toml(path: Path, data: dict) -> None:
    lines: list[str] = []
    for section in ("ollama", "docker", "diagnostics"):
        block = data.get(section)
        if not isinstance(block, dict) or not block:
            continue
        lines.append(f"[{section}]")
        for key, value in block.items():
            lines.append(f"{key} = {_toml_literal(value)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).strip()
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def save_ollama_config(path: Path, *, host: str, model: str) -> None:
    """Merge [ollama] host and model into an existing config file or create one."""
    data: dict = _load_toml(path) if path.is_file() else {}
    ollama = dict(data.get("ollama") if isinstance(data.get("ollama"), dict) else {})
    ollama["host"] = normalize_ollama_host(host, require_ip=True)
    ollama["model"] = model
    data["ollama"] = ollama
    if "docker" not in data:
        data["docker"] = {"timeout": int(DEFAULT_DOCKER_TIMEOUT)}
    if "diagnostics" not in data:
        data["diagnostics"] = {"verbose": False}
    _write_toml(path, data)
