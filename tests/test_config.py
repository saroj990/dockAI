import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dockai.cli import app
from dockai.config import load_settings, normalize_ollama_host, save_ollama_config
from dockai.llm.ollama import OllamaNotFoundError
from dockai.setup_config import SetupConfigError, run_setup_config


def _isolate_config_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCKAI_CONFIG", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("DOCKAI_MODEL", raising=False)
    monkeypatch.delenv("DOCKAI_OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("DOCKAI_DOCKER_TIMEOUT", raising=False)
    monkeypatch.delenv("DOCKAI_DEBUG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


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


def test_normalize_ollama_host_shorthand_ip():
    assert normalize_ollama_host("10.0.0.5") == "http://10.0.0.5:11434"
    assert normalize_ollama_host("10.0.0.5:8080") == "http://10.0.0.5:8080"
    assert normalize_ollama_host("http://10.0.0.5") == "http://10.0.0.5:11434"


def test_normalize_ollama_host_requires_ip_when_configured():
    with pytest.raises(ValueError, match="IP address is required"):
        normalize_ollama_host("", require_ip=True)
    with pytest.raises(ValueError, match="valid IP address"):
        normalize_ollama_host("not-an-ip", require_ip=True)


def test_setup_local_ip_without_scheme(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    prompts = iter(["127.0.0.1", 1])

    def fake_url():
        return next(prompts)

    def fake_index(_models: list[str]) -> int:
        return next(prompts)

    def fake_list(host: str) -> list[str]:
        assert host == "http://127.0.0.1:11434"
        return ["qwen2.5:3b"]

    path = run_setup_config(
        prompt_url=fake_url,
        prompt_model_index=fake_index,
        list_models=fake_list,
    )
    assert path == tmp_path / "dockai.toml"
    settings = load_settings()
    assert settings.ollama_host == "http://127.0.0.1:11434"
    assert settings.ollama_model == "qwen2.5:3b"


def test_setup_blank_url_rejected(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    with pytest.raises(SetupConfigError, match="IP address is required"):
        run_setup_config(
            prompt_url=lambda: "",
            prompt_model_index=lambda _m: 1,
            list_models=lambda _h: ["m"],
        )


def test_setup_remote_url_is_saved(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    prompts = iter(["10.0.0.5", 2])

    def fake_url():
        return next(prompts)

    def fake_index(_models: list[str]) -> int:
        return next(prompts)

    def fake_list(host: str) -> list[str]:
        assert host == "http://10.0.0.5:11434"
        return ["llama3.1:8b", "gemma3:4b"]

    run_setup_config(
        prompt_url=fake_url,
        prompt_model_index=fake_index,
        list_models=fake_list,
    )
    settings = load_settings()
    assert settings.ollama_host == "http://10.0.0.5:11434"
    assert settings.ollama_model == "gemma3:4b"


def test_setup_ollama_not_found(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    cfg = tmp_path / "dockai.toml"
    cfg.write_text('[ollama]\nmodel = "keep-me"\nhost = "http://old:11434"\n', encoding="utf-8")

    def fake_list(_host: str) -> list[str]:
        raise OllamaNotFoundError("Ollama not found at http://203.0.113.99:11434.")

    with pytest.raises(SetupConfigError, match="Ollama not found"):
        run_setup_config(
            config_path=cfg,
            prompt_url=lambda: "203.0.113.99",
            prompt_model_index=lambda _m: 1,
            list_models=fake_list,
        )

    with cfg.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["ollama"]["model"] == "keep-me"


def test_setup_empty_model_list(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    cfg = tmp_path / "dockai.toml"
    cfg.write_text('[ollama]\nmodel = "keep-me"\n', encoding="utf-8")

    with pytest.raises(SetupConfigError, match="No models are available"):
        run_setup_config(
            config_path=cfg,
            prompt_url=lambda: "127.0.0.1",
            prompt_model_index=lambda _m: 1,
            list_models=lambda _h: [],
        )

    with cfg.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["ollama"]["model"] == "keep-me"


def test_load_settings_normalizes_shorthand_host_in_file(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    cfg = tmp_path / "dockai.toml"
    cfg.write_text('[ollama]\nhost = "10.0.0.5"\nmodel = "m"\n', encoding="utf-8")
    settings = load_settings()
    assert settings.ollama_host == "http://10.0.0.5:11434"


def test_config_command_still_prints_without_prompt(monkeypatch, tmp_path: Path):
    _isolate_config_env(monkeypatch, tmp_path)
    cfg = tmp_path / "dockai.toml"
    cfg.write_text(
        '[ollama]\nhost = "http://h:11434"\nmodel = "saved-model"\n',
        encoding="utf-8",
    )

    def fail_prompt(*_args, **_kwargs):
        raise AssertionError("config must not prompt")

    monkeypatch.setattr("typer.prompt", fail_prompt)
    result = CliRunner().invoke(app, ["config"])
    assert result.exit_code == 0
    assert "http://h:11434" in result.output
    assert "saved-model" in result.output


def test_save_ollama_config_preserves_other_sections(tmp_path: Path):
    cfg = tmp_path / "dockai.toml"
    cfg.write_text(
        """
[ollama]
model = "old"
timeout = 99

[docker]
timeout = 15
""".strip(),
        encoding="utf-8",
    )
    save_ollama_config(cfg, host="http://127.0.0.1:11434", model="new-model")
    settings = load_settings(config_path=cfg)
    assert settings.ollama_model == "new-model"
    assert settings.ollama_timeout == 99.0
    assert settings.docker_timeout == 15.0
