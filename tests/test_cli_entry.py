import sys

from dockai.cli import main_cli


def test_bare_prompt_rewrites_to_ask(monkeypatch):
    seen: list[str] = []

    def fake_app():
        seen.extend(sys.argv)

    monkeypatch.setattr("dockai.cli.app", fake_app)
    monkeypatch.setattr(sys, "argv", ["dockai", "show running containers"])
    main_cli()
    assert seen[1] == "ask"
    assert seen[2] == "show running containers"


def test_subcommand_not_rewritten(monkeypatch):
    seen: list[str] = []

    def fake_app():
        seen.extend(sys.argv)

    monkeypatch.setattr("dockai.cli.app", fake_app)
    monkeypatch.setattr(sys, "argv", ["dockai", "containers", "--all"])
    main_cli()
    assert seen[1] == "containers"


def test_stop_subcommand_not_rewritten(monkeypatch):
    seen: list[str] = []

    def fake_app():
        seen.extend(sys.argv)

    monkeypatch.setattr("dockai.cli.app", fake_app)
    monkeypatch.setattr(sys, "argv", ["dockai", "stop", "api-server"])
    main_cli()
    assert seen[1] == "stop"
