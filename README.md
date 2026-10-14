# dockai

Natural-language Docker CLI agent. Talk to your local Docker Engine in plain English, or use fast direct commands (no LLM).

## Fresh machine setup (clone → first command)

Follow these steps **in order** on a new Mac/Linux machine.

### 0. Prerequisites (install once)

| Need | Why | Check |
|------|-----|--------|
| **Git** | Clone the repo | `git --version` |
| **Python 3.11+** | Runtime | `python3 --version` |
| **Docker Engine** | Container source of truth | `docker ps` (must work **without** sudo for your user) |
| **Ollama** | Natural-language mode only | `ollama --version` |

- Docker: install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Windows) or Docker Engine (Linux). Start it, then confirm `docker ps` works.
- Ollama: install from [https://ollama.com](https://ollama.com), then start it (`ollama serve` if it is not already running).
- You do **not** need Ollama for `dockai containers`, `logs`, `stop`, etc.

### 1. Clone

```bash
git clone git@github.com:saroj990/dockAI.git
cd dockAI
```

HTTPS alternative:

```bash
git clone https://github.com/saroj990/dockAI.git
cd dockAI
```

### 2. Create a virtualenv and install dockai

Always work **inside** the venv. If you skip activation, `dockai` will not be found.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Confirm the CLI is available:

```bash
which dockai
dockai --version
dockai --help
```

If `dockai: command not found`, you are not in the venv — run `source .venv/bin/activate` again.

### 3. Config file (recommended)

```bash
cp dockai.example.toml dockai.toml
```

Edit `dockai.toml` and set a model you will actually pull (example for speed):

```toml
[ollama]
host = "http://127.0.0.1:11434"
model = "qwen2.5:3b"    # must match `ollama list`
timeout = 120

[docker]
timeout = 60

[diagnostics]
verbose = false
```

Show what dockai will use:

```bash
dockai config
```

**Config search order:** `DOCKAI_CONFIG` → `./dockai.toml` → `~/.config/dockai/config.toml`  
**Precedence:** CLI flags > environment variables > config file > defaults

| Setting | Config | Environment | CLI |
|---------|--------|-------------|-----|
| Ollama host | `[ollama] host` | `OLLAMA_HOST` | — |
| Model | `[ollama] model` | `DOCKAI_MODEL` | `--model` |
| Ollama timeout | `[ollama] timeout` | `DOCKAI_OLLAMA_TIMEOUT` | — |
| Docker timeout | `[docker] timeout` | `DOCKAI_DOCKER_TIMEOUT` | — |
| Verbose logs | `[diagnostics] verbose` | `DOCKAI_DEBUG=1` | `-v` / `--verbose` |
| Config path | — | `DOCKAI_CONFIG=/path/to.toml` | `--config` |

Env vars are **optional** if `dockai.toml` is set. Use them only to override without editing the file.

### 4. Pull the Ollama model (NL mode)

The model name in config **must** exist locally:

```bash
ollama pull qwen2.5:3b          # or whatever you set in dockai.toml
ollama list                     # confirm the name matches exactly
curl -s http://127.0.0.1:11434/api/tags | head  # API reachable?
```

Other workable options: `llama3.1:8b` (higher quality, slower), `gemma3:4b` (faster, weaker tools).

### 5. Smoke test

```bash
# Always activate first (new terminal)
cd /path/to/dockAI
source .venv/bin/activate

# 1) Docker-only (should be fast, no Ollama needed)
dockai containers

# 2) Natural language (needs Ollama + model)
dockai "show running containers"

# 3) Interactive
dockai chat
```

Every NL reply prints stage timings, e.g.:

```text
Completed in 800 ms
  · ollama #1: 600 ms
  · docker list_containers: 150 ms
```

---

## Day-to-day usage

```bash
cd /path/to/dockAI
source .venv/bin/activate

# Fast path (no LLM)
dockai containers
dockai containers --all
dockai logs <name> -n 25
dockai search flink
dockai uptime
dockai inspect <name>
dockai stop <name>              # confirms, then applies
dockai start <name>
dockai restart <name>

# Natural language
dockai "show running containers"
dockai ask "show the last 25 lines of api-server logs"
dockai chat
dockai -v "show running containers"   # tool diagnostics
```

---

## Common setup mistakes

| Problem | Cause | Fix |
|---------|--------|-----|
| `dockai: command not found` | venv not activated, or install skipped | `source .venv/bin/activate` then `pip install -e ".[dev]"` |
| `Docker Engine is unavailable` | Docker not running / no socket permission | Start Docker Desktop; re-check `docker ps` |
| Ollama connection errors | Ollama not running or wrong host | `ollama serve`; set `host` in `dockai.toml` |
| Model not found / bad tool calls | Config model ≠ pulled model | `ollama list` and match `[ollama] model` exactly |
| `python: command not found` | Only `python3` on PATH | Use `python3 -m venv .venv` |
| Wrong Python (3.9/3.10) | Old system Python | Install 3.11+ and recreate `.venv` |
| Slow answers (10–20s+) | Large model + LLM summary | Use `qwen2.5:3b`; prefer `dockai containers` for lists |

---

## Testing (optional)

```bash
source .venv/bin/activate
pytest                  # unit + acceptance (mocked Docker)
pytest -m integration   # disposable alpine container (needs Docker)
```

---

## Performance notes

- Direct commands ≈ `docker` speed.
- NL mode cost is mostly **Ollama**, not Docker.
- **Table-first:** simple list / uptime / search / logs / inspect skip the second LLM summary.
- **NL shortcuts:** common phrases skip Ollama entirely (timings show `shortcut:list` / `shortcut:logs`). Troubleshooting / vague asks still use the model.

---

## Safety

- Only predefined tools (no shell execution of model output).
- start / stop / restart require explicit confirmation.
- Facts come from Docker, not model invention.
- delete / prune / Docker Desktop control → clear **Not supported** refusal.

---

## Roadmap

| Phase | Status |
|-------|--------|
| 1 Docker foundation | Done |
| 2 LLM integration | Done |
| 3 Interactive chat | Done |
| 4 Safe mutations | Done |
| 5 Hardening | Done |

Open issues / backlog: see `GITHUB_ISSUES.md`.
