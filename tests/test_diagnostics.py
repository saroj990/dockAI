from dockai.diagnostics import configure_diagnostics, debug_enabled
from dockai.llm.ollama import _default_timeout


def test_debug_env(monkeypatch):
    monkeypatch.delenv("DOCKAI_DEBUG", raising=False)
    assert debug_enabled() is False
    monkeypatch.setenv("DOCKAI_DEBUG", "1")
    assert debug_enabled() is True
    configure_diagnostics(verbose=True)


def test_ollama_timeout_env(monkeypatch):
    monkeypatch.setenv("DOCKAI_OLLAMA_TIMEOUT", "30")
    assert _default_timeout() == 30.0
