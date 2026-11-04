"""Interactive terminal prompts (arrow-key menus when stdin is a TTY)."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
import typer
from rich.console import Console, RenderableType
from rich.live import Live
from rich.table import Table


def move_menu_selection(current: int, direction: str, count: int) -> int:
    """0-based index; wraps at ends. direction is ``up`` or ``down``."""
    if count <= 0:
        return 0
    if direction == "up":
        return (current - 1) % count
    if direction == "down":
        return (current + 1) % count
    return current


def resolve_menu_keys(keys: Sequence[str], count: int) -> int:
    """
    Apply a sequence of menu keys and return the 1-based choice index.

    Keys: ``up``, ``down``, ``enter``. Raises ValueError if ``enter`` never sent.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    selected = 0
    for key in keys:
        normalized = key.strip().lower()
        if normalized == "enter":
            return selected + 1
        if normalized in {"up", "down"}:
            selected = move_menu_selection(selected, normalized, count)
    raise ValueError("menu ended without enter")


def _render_model_menu(models: Sequence[str], selected: int) -> RenderableType:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=2)
    table.add_column()
    for idx, name in enumerate(models):
        marker = "▸" if idx == selected else " "
        num = idx + 1
        if idx == selected:
            table.add_row(marker, f"[bold green]{num}. {name}[/bold green]")
        else:
            table.add_row(marker, f"{num}. {name}")
    return table


def _read_menu_key() -> str:
    """Read one menu key from a TTY (arrow keys, Enter, or typed digits)."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        rest = sys.stdin.read(2)
        if rest == "[A":
            return "up"
        if rest == "[B":
            return "down"
        return "ignore"
    if ch in {"\r", "\n"}:
        return "enter"
    if ch in {"\x03", "\x04"}:
        raise KeyboardInterrupt
    if ch.isdigit():
        return f"digit:{ch}"
    return "ignore"


def _run_model_menu_loop(
    models: Sequence[str],
    *,
    console: Console,
    read_key: Callable[[], str],
) -> int:
    selected = 0
    digit_buffer = ""
    console.print("[bold]Available models[/bold] (↑↓ move, Enter confirm, or type 1–N)")
    with Live(_render_model_menu(models, selected), console=console, refresh_per_second=20) as live:
        while True:
            key = read_key()
            if key == "up":
                selected = move_menu_selection(selected, "up", len(models))
                digit_buffer = ""
            elif key == "down":
                selected = move_menu_selection(selected, "down", len(models))
                digit_buffer = ""
            elif key.startswith("digit:"):
                digit_buffer += key.split(":", 1)[1]
                if digit_buffer.isdigit():
                    value = int(digit_buffer)
                    if 1 <= value <= len(models):
                        selected = value - 1
            elif key == "enter":
                if digit_buffer.isdigit():
                    value = int(digit_buffer)
                    if 1 <= value <= len(models):
                        return value
                return selected + 1
            elif key == "ignore":
                continue
            live.update(_render_model_menu(models, selected))


def prompt_numbered_model_choice(
    models: Sequence[str],
    *,
    console: Console | None = None,
    is_tty: Callable[[], bool] | None = None,
    read_key: Callable[[], str] | None = None,
) -> int:
    """
    Choose 1..N with ↑/↓ (wraps) and Enter, or type a number + Enter.

    Falls back to Typer's integer prompt when stdin is not a TTY.
    """
    if not models:
        raise ValueError("models must not be empty")
    out = console or Console()
    tty_check = is_tty or sys.stdin.isatty
    if read_key is not None:
        return _run_model_menu_loop(models, console=out, read_key=read_key)
    if not tty_check():
        return _prompt_model_index_fallback(models, console=out)

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return _run_model_menu_loop(models, console=out, read_key=_read_menu_key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _prompt_model_index_fallback(models: Sequence[str], *, console: Console) -> int:
    console.print("[bold]Available models:[/bold]")
    for idx, name in enumerate(models, start=1):
        console.print(f"  {idx}. {name}")
    return typer.prompt("Select model number", type=int)
