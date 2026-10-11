from dockai.formatting import format_elapsed


def test_format_elapsed_ms():
    assert format_elapsed(0.42) == "420 ms"


def test_format_elapsed_seconds():
    assert format_elapsed(12.34) == "12.3s"


def test_format_elapsed_minutes():
    assert format_elapsed(65.2) == "1m 5.2s"
