from pathlib import Path

from dockai.config import load_settings


def test_load_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCKAI_CONFIG", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("DOCKAI_MODEL", raising=False)
    monkeypatch.delenv("DOCKAI_OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("DOCKAI_DOCKER_TIMEOUT", raising=False)
    monkeypatch.delenv("DOCKAI_DEBUG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    settings = load_settings()
    assert settings.ollama_host == "http://127.0.0.1:11434"
    assert settings.ollama_model == "llama3.1:8b"
    assert settings.config_path is None


def test_load_from_toml(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "dockai.toml"
    cfg.write_text(
        """
[ollama]
host = "http://10.0.0.5:11434"
model = "gemma3:4b"
timeout = 45

[docker]
timeout = 15

[diagnostics]
verbose = true
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCKAI_CONFIG", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("DOCKAI_MODEL", raising=False)
    monkeypatch.delenv("DOCKAI_OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("DOCKAI_DOCKER_TIMEOUT", raising=False)
    monkeypatch.delenv("DOCKAI_DEBUG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    settings = load_settings()
    assert settings.config_path == cfg
    assert settings.ollama_host == "http://10.0.0.5:11434"
    assert settings.ollama_model == "gemma3:4b"
    assert settings.ollama_timeout == 45.0
    assert settings.docker_timeout == 15.0
    assert settings.verbose is True


def test_env_overrides_file(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "custom.toml"
    cfg.write_text(
        """
[ollama]
host = "http://file-host:11434"
model = "from-file"
timeout = 10
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCKAI_CONFIG", str(cfg))
    monkeypatch.setenv("OLLAMA_HOST", "http://env-host:11434")
    monkeypatch.setenv("DOCKAI_MODEL", "from-env")
    monkeypatch.setenv("DOCKAI_OLLAMA_TIMEOUT", "99")
    settings = load_settings()
    assert settings.ollama_host == "http://env-host:11434"
    assert settings.ollama_model == "from-env"
    assert settings.ollama_timeout == 99.0


def test_cli_model_overrides_all(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "custom.toml"
    cfg.write_text('[ollama]\nmodel = "from-file"\n', encoding="utf-8")
    monkeypatch.setenv("DOCKAI_CONFIG", str(cfg))
    monkeypatch.setenv("DOCKAI_MODEL", "from-env")
    settings = load_settings(model="from-cli")
    assert settings.ollama_model == "from-cli"
