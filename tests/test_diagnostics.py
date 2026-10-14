from dockai.config import load_settings
from dockai.diagnostics import configure_diagnostics, debug_enabled


def test_debug_env(monkeypatch):
    monkeypatch.delenv("DOCKAI_DEBUG", raising=False)
    assert debug_enabled() is False
    monkeypatch.setenv("DOCKAI_DEBUG", "1")
    assert debug_enabled() is True
    configure_diagnostics(verbose=True)


def test_ollama_timeout_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("DOCKAI_CONFIG", raising=False)
    monkeypatch.setenv("DOCKAI_OLLAMA_TIMEOUT", "30")
    settings = load_settings()
    assert settings.ollama_timeout == 30.0
