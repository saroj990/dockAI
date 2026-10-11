"""Uptime helpers grounded in Docker start times."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_docker_time(value: str | None) -> datetime | None:
    """Parse Docker RFC3339 timestamps; treat zero-time as missing."""
    if not value:
        return None
    if value.startswith("0001-01-01"):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_elapsed(seconds: float) -> str:
    """Format a positive duration for terminal display."""
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def compute_uptime(
    *,
    status: str,
    started_at: str | None,
    finished_at: str | None = None,
    now: datetime | None = None,
) -> dict:
    """
    Return a clear uptime/state summary.

    Running containers get elapsed time from StartedAt.
    Stopped containers report last start and finished time, not uptime.
    """
    start = parse_docker_time(started_at)
    finish = parse_docker_time(finished_at)
    current = now or datetime.now(timezone.utc)
    running = status.lower().startswith("running") or status.lower() == "up"

    if running and start is not None:
        elapsed = (current - start).total_seconds()
        return {
            "kind": "uptime",
            "label": "Uptime",
            "value": format_elapsed(elapsed),
            "started_at": start.isoformat(),
            "finished_at": None,
        }

    return {
        "kind": "stopped",
        "label": "State",
        "value": status,
        "started_at": start.isoformat() if start else None,
        "finished_at": finish.isoformat() if finish else None,
    }
