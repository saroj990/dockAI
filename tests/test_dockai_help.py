"""Meta questions about dockai commands — no generic docker CLI lecture."""

from __future__ import annotations

from unittest.mock import MagicMock

from dockai.agent.help import (
    is_dockai_help_request,
    load_commands_help_markdown,
    try_dockai_help_response,
)
from dockai.agent.loop import run_agent
from tests.test_agent import ScriptedLLM


def test_is_dockai_help_request_matches():
    assert is_dockai_help_request("what are the commands i can run")
    assert is_dockai_help_request("show me commands?")
    assert is_dockai_help_request("what commands are there")
    assert is_dockai_help_request("how do I use dockai")


def test_is_dockai_help_request_rejects_container_diagnosis():
    assert not is_dockai_help_request("why is my pg_tileserv restarting")
    assert not is_dockai_help_request("what is wrong with postgis")
    assert not is_dockai_help_request("docker ps -a")


def test_commands_help_markdown_lists_dockai_not_docker_ps():
    md = load_commands_help_markdown()
    assert "dockai containers" in md
    assert "how many running containers" in md
    assert "logs for" in md
    assert "docker ps\n" not in md
    assert "docker run" not in md


def test_try_dockai_help_response():
    resp = try_dockai_help_response("what commands can i run")
    assert resp is not None
    assert "dockai chat" in resp.markdown


def test_run_agent_help_skips_llm():
    from dockai.llm.base import ChatMessage

    llm = ScriptedLLM(
        [ChatMessage(role="assistant", content="docker ps is the command")]
    )
    result = run_agent(
        "what are the commands i can run",
        llm=llm,
        client=MagicMock(),
    )
    assert result.presentation is not None
    assert result.presentation["kind"] == "help"
    assert "dockai containers" in result.presentation["markdown"]
    assert len(llm.calls) == 0
    assert result.timings == []


def test_run_agent_help_phrase_show_commands():
    llm = ScriptedLLM([])
    result = run_agent("show me commands?", llm=llm, client=MagicMock())
    assert result.presentation["kind"] == "help"
    assert llm.calls == []
