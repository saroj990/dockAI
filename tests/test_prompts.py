"""Arrow-key and fallback prompts for setup config."""

from __future__ import annotations

import pytest

from dockai.prompts import (
    move_menu_selection,
    prompt_numbered_model_choice,
    resolve_menu_keys,
)


def test_move_menu_selection_wraps():
    assert move_menu_selection(0, "up", 3) == 2
    assert move_menu_selection(2, "down", 3) == 0
    assert move_menu_selection(1, "down", 3) == 2


def test_resolve_menu_keys_down_down_enter():
    assert resolve_menu_keys(["down", "down", "enter"], 3) == 3


def test_resolve_menu_keys_up_from_first_selects_last():
    assert resolve_menu_keys(["up", "enter"], 3) == 3


def test_prompt_numbered_model_choice_fallback(monkeypatch):
    monkeypatch.setattr("dockai.prompts.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("dockai.prompts.typer.prompt", lambda *_a, **_k: 2)
    assert prompt_numbered_model_choice(["a", "b", "c"]) == 2


def test_prompt_numbered_model_choice_tty_simulated():
    models = ["nomic-embed-text:latest", "qwen2.5:3b", "qwen3:8b"]
    keys = iter(["down", "enter"])

    def fake_read() -> str:
        return next(keys)

    index = prompt_numbered_model_choice(
        models,
        is_tty=lambda: True,
        read_key=fake_read,
    )
    assert index == 2
    assert models[index - 1] == "qwen2.5:3b"


def test_prompt_numbered_model_choice_digit_enter():
    models = ["a", "b", "c"]
    keys = iter(["digit:3", "enter"])

    def fake_read() -> str:
        return next(keys)

    assert (
        prompt_numbered_model_choice(
            models,
            is_tty=lambda: True,
            read_key=fake_read,
        )
        == 3
    )


def test_resolve_menu_keys_requires_enter():
    with pytest.raises(ValueError, match="enter"):
        resolve_menu_keys(["down"], 3)
