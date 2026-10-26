"""Casual chat detection."""

from __future__ import annotations

import pytest

from dockai.agent.casual import is_casual_chat_turn


@pytest.mark.parametrize(
    "phrase",
    [
        "hello",
        "Hello!",
        "hey there",
        "how are you",
        "thanks",
        "good morning",
    ],
)
def test_casual_phrases(phrase: str):
    assert is_casual_chat_turn(phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "hello show me containers",
        "hi logs for pg_tileserv",
        "why is api restarting",
    ],
)
def test_not_casual_when_docker_cue(phrase: str):
    assert not is_casual_chat_turn(phrase)
