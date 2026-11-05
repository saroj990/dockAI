"""Interactive chat exit phrases and confirmation."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from dockai.cli import app, is_chat_exit_request
from dockai.config import Settings


def test_is_chat_exit_request():
    assert is_chat_exit_request("exit")
    assert is_chat_exit_request("  BYE  ")
    assert is_chat_exit_request("goodbye")
    assert is_chat_exit_request("bye for now")
    assert not is_chat_exit_request("exit db")
    assert not is_chat_exit_request("show logs")


def test_chat_requires_confirmation_to_exit():
    settings = Settings(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        config_path=None,
        chat_hints=False,
    )

    with (
        patch("dockai.cli._ctx_settings", return_value=settings),
        patch("dockai.cli._prepare_ollama_settings", return_value=settings),
        patch("dockai.cli.get_client"),
        patch("dockai.cli.OllamaProvider") as provider_cls,
        patch("dockai.cli.ChatSession") as session_cls,
        patch("dockai.cli.typer.confirm", side_effect=[False, True]) as confirm,
    ):
        provider_cls.return_value.close = lambda: None
        session_cls.return_value.ask.return_value = type(
            "R",
            (),
            {
                "answer": "",
                "presentation": None,
                "timings": [],
                "pending_action": None,
            },
        )()
        session_cls.return_value.focus_container = None
        result = CliRunner().invoke(app, ["chat"], input="exit\nexit\n")

    assert result.exit_code == 0
    assert confirm.call_count == 2
