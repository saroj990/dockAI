from datetime import datetime, timezone

from dockai.uptime import compute_uptime, format_elapsed, parse_docker_time


def test_parse_docker_time_zero_is_none():
    assert parse_docker_time("0001-01-01T00:00:00Z") is None


def test_parse_docker_time_rfc3339():
    dt = parse_docker_time("2026-10-11T04:00:00Z")
    assert dt == datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)


def test_format_elapsed():
    assert format_elapsed(3661) == "1h 1m 1s"
    assert format_elapsed(45) == "45s"


def test_compute_uptime_running():
    now = datetime(2026, 10, 11, 5, 0, tzinfo=timezone.utc)
    result = compute_uptime(
        status="running",
        started_at="2026-10-11T04:00:00Z",
        now=now,
    )
    assert result["kind"] == "uptime"
    assert result["value"] == "1h 0m 0s"


def test_compute_uptime_stopped_not_described_as_running():
    result = compute_uptime(
        status="exited",
        started_at="2026-10-11T04:00:00Z",
        finished_at="2026-10-11T04:30:00Z",
    )
    assert result["kind"] == "stopped"
    assert result["value"] == "exited"
    assert result["started_at"] is not None
    assert result["finished_at"] is not None
