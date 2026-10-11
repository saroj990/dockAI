"""Optional diagnostic logging (no secrets)."""

from __future__ import annotations

import logging
import os
from typing import Any

LOGGER = logging.getLogger("dockai")


def debug_enabled() -> bool:
    return os.getenv("DOCKAI_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def configure_diagnostics(*, verbose: bool = False) -> None:
    """Enable dockai debug logs when --verbose or DOCKAI_DEBUG is set."""
    if not verbose and not debug_enabled():
        return
    if LOGGER.handlers:
        LOGGER.setLevel(logging.DEBUG)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[dockai] %(levelname)s: %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.debug("Diagnostics enabled")


def log_tool_call(name: str, arguments: dict[str, Any]) -> None:
    safe = {k: v for k, v in arguments.items() if "password" not in k.lower()}
    LOGGER.debug("tool call name=%s args=%s", name, safe)


def log_tool_result(name: str, result: dict[str, Any]) -> None:
    ok = result.get("ok")
    if ok:
        LOGGER.debug("tool ok name=%s", name)
    else:
        LOGGER.debug("tool error name=%s error=%s", name, result.get("error"))
