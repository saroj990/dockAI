"""Rich terminal formatting for structured Docker results."""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Iterable

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()

# Strip a prior elapsed suffix when refreshing status text.
_ELAPSED_SUFFIX_RE = re.compile(r"\s*\([^)]+\)\s*$")
_RICH_TAG_RE = re.compile(r"\[\/?[^\]]+\]")


def print_error(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")


def print_info(message: str) -> None:
    console.print(message)


def append_elapsed_to_status_message(message: str, elapsed_seconds: float) -> str:
    """Append wall time for spinner text, reusing footer formatting rules."""
    plain = _RICH_TAG_RE.sub("", message).strip()
    base = _ELAPSED_SUFFIX_RE.sub("", plain).strip()
    return f"{base} ({format_elapsed(elapsed_seconds)})"


class ElapsedStatusHandle:
    """Rich status handle that keeps elapsed time on the spinner line."""

    def __init__(
        self,
        status: Any,
        start: float,
        *,
        tick_interval: float = 0.5,
    ) -> None:
        self._status = status
        self._start = start
        self._tick = tick_interval
        self._message = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def update(self, message: str) -> None:
        """Set stage text; elapsed suffix is recomputed from the same start time."""
        self._message = _RICH_TAG_RE.sub("", message).strip()
        self._render()

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(self._tick):
                self._render()

        self._thread = threading.Thread(target=loop, daemon=True, name="dockai-status-tick")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _render(self) -> None:
        elapsed = time.perf_counter() - self._start
        text = append_elapsed_to_status_message(self._message, elapsed)
        self._status.update(f"[cyan]{text}[/cyan]")


@contextmanager
def busy_status(
    message: str = "Working on it — fetching results, please wait…",
    *,
    show_elapsed: bool = True,
    tick_interval: float = 0.5,
) -> Iterator[Any]:
    """Show a spinner while work runs; optionally tick elapsed time on the same line."""
    start = time.perf_counter()
    with console.status(f"[cyan]{message}[/cyan]", spinner="dots") as status:
        if not show_elapsed:
            yield status
            return
        handle = ElapsedStatusHandle(
            status, start, tick_interval=tick_interval
        )
        handle.update(message)
        handle.start()
        try:
            yield handle
        finally:
            handle.stop()


def format_elapsed(seconds: float) -> str:
    """Human-readable duration for CLI footers."""
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rem = divmod(seconds, 60)
    return f"{int(minutes)}m {rem:.1f}s"


def print_elapsed(
    seconds: float,
    timings: list[tuple[str, float]] | None = None,
) -> None:
    console.print(f"[dim]Completed in {format_elapsed(seconds)}[/dim]")
    if not timings:
        return
    for label, stage in timings:
        console.print(f"[dim]  · {label}: {format_elapsed(stage)}[/dim]")


def container_table(
    containers: Iterable[dict[str, Any]],
    *,
    columns: list[str] | None = None,
    title: str | None = None,
) -> Table:
    """Build a readable table; default columns cover ID, name, status, uptime."""
    cols = columns or ["id", "name", "status", "uptime"]
    table = Table(title=title, show_header=True, header_style="bold")
    headers = {
        "id": "ID",
        "name": "Name",
        "status": "Status",
        "image": "Image",
        "uptime": "Uptime",
        "restarts": "Restarts",
    }
    for key in cols:
        table.add_column(headers.get(key, key.title()))

    rows = list(containers)
    if not rows:
        table.add_row(*(["—"] * len(cols)))
        return table

    for item in rows:
        values: list[str] = []
        for key in cols:
            if key == "uptime":
                uptime = item.get("uptime") or {}
                if uptime.get("kind") == "uptime":
                    values.append(uptime.get("value") or "—")
                else:
                    started = uptime.get("started_at") or "—"
                    values.append(f"{uptime.get('value', item.get('status', '—'))} (last start: {started})")
            elif key == "restarts":
                values.append(str(item.get("restarts", 0)))
            else:
                values.append(str(item.get(key, "—")))
        table.add_row(*values)
    return table


def print_containers(
    containers: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
    title: str | None = None,
    empty_message: str = "No containers found.",
) -> None:
    if not containers:
        print_info(empty_message)
        return
    console.print(container_table(containers, columns=columns, title=title))


def print_inspect(summary: dict[str, Any]) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    fields = [
        ("Name", summary.get("name")),
        ("ID", summary.get("id")),
        ("Status", summary.get("status")),
        ("Image", summary.get("image")),
        ("Restart count", summary.get("restarts")),
        ("Restarting", summary.get("restarting")),
        ("Exit code", summary.get("exit_code")),
        ("OOM killed", summary.get("oom_killed")),
        ("Health", summary.get("health")),
        ("PID", summary.get("pid")),
        ("Started at", summary.get("started_at")),
        ("Finished at", summary.get("finished_at")),
    ]
    uptime = summary.get("uptime") or {}
    fields.append((uptime.get("label", "Uptime"), uptime.get("value")))
    if summary.get("error"):
        fields.append(("Error", summary["error"]))
    for label, value in fields:
        if value is None:
            continue
        table.add_row(label, str(value))
    console.print(table)


def print_troubleshoot(result: dict[str, Any]) -> None:
    """Render inspect facts and deterministic log signal highlights."""
    inspect_data = result.get("inspect") or {}
    analysis = result.get("analysis") or {}
    logs_meta = result.get("logs") or {}

    table = Table(title=f"Troubleshoot {result.get('container')} ({result.get('id')})")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    rows = [
        ("Status", inspect_data.get("status")),
        ("Restarts", inspect_data.get("restarts")),
        ("Restarting", inspect_data.get("restarting")),
        ("Exit code", inspect_data.get("exit_code")),
        ("OOM killed", inspect_data.get("oom_killed")),
        ("Health", inspect_data.get("health")),
        ("Docker error", inspect_data.get("error")),
    ]
    uptime = inspect_data.get("uptime") or {}
    rows.append((uptime.get("label", "Uptime"), uptime.get("value")))
    for label, value in rows:
        if value is None:
            continue
        table.add_row(label, str(value))
    console.print(table)

    console.print("[bold]Log signals (from Docker)[/bold]")
    highlights = analysis.get("highlight_lines") or []
    if not highlights:
        console.print("[dim]No error-like lines in the analyzed log tail.[/dim]")
    else:
        for item in highlights:
            cats = ", ".join(item.get("categories") or [])
            console.print(
                f"  [dim]L{item.get('line')}[/dim] [{cats}] {item.get('text', '')}"
            )

    note = logs_meta.get("note")
    if note:
        console.print(f"[dim]{note}[/dim]")
    if logs_meta.get("truncated"):
        console.print("[dim]Log output was truncated for safety.[/dim]")


def print_logs(result: dict[str, Any]) -> None:
    header = Text()
    header.append(f"{result['container']} ({result['id']})", style="bold")
    header.append(f" — {result['note']}")
    console.print(header)
    if result.get("empty"):
        print_info("No log output available.")
        return
    console.print(result["logs"], end="" if result["logs"].endswith("\n") else "\n")
    if result.get("truncated"):
        print_info("[dim]Log output was truncated for safety.[/dim]")


def print_search(
    result: dict[str, Any],
    *,
    columns: list[str] | None = None,
) -> None:
    scope = result["scope"]
    print_info(
        f"Search for [bold]{result['keyword']}[/bold] "
        f"(scope: {scope} containers) — {result['count']} match(es)."
    )
    print_containers(
        result["matches"],
        columns=columns or ["id", "name", "status", "image", "uptime"],
        empty_message="No containers matched that keyword.",
    )
