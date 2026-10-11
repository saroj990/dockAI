# dockai

Natural-language Docker CLI agent (MVP through Phase 5 hardening).

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requirements:

- Python 3.11+
- Local Docker Engine access for the current user
- [Ollama](https://ollama.com) + a tool-capable model for natural-language modes

```bash
ollama pull llama3.1:8b
```

### Configuration

Copy the example config, then edit host/model as needed:

```bash
cp dockai.example.toml dockai.toml
# or: mkdir -p ~/.config/dockai && cp dockai.example.toml ~/.config/dockai/config.toml
dockai config          # show resolved settings
```

Search order: `DOCKAI_CONFIG` → `./dockai.toml` → `~/.config/dockai/config.toml`.

Precedence: **CLI flags > environment variables > config file > defaults**.

| Setting | Config key | Env | CLI |
|---------|------------|-----|-----|
| Ollama host | `[ollama] host` | `OLLAMA_HOST` | — |
| Model | `[ollama] model` | `DOCKAI_MODEL` | `--model` |
| Ollama timeout | `[ollama] timeout` | `DOCKAI_OLLAMA_TIMEOUT` | — |
| Docker timeout | `[docker] timeout` | `DOCKAI_DOCKER_TIMEOUT` | — |
| Verbose logs | `[diagnostics] verbose` | `DOCKAI_DEBUG` | `-v` / `--verbose` |
| Config path | — | `DOCKAI_CONFIG` | `--config` |

## Quick examples

```bash
# Fast path (no LLM)
dockai containers
dockai logs api-server -n 25
dockai search flink
dockai stop api-server          # shows impact, asks to confirm, verifies result

# Natural language (LLM; slower — time is mostly Ollama)
dockai "show running containers"
dockai ask "show the last 25 lines of api-server logs" --verbose
dockai chat
```

## Roadmap

| Phase | Status | Focus |
|-------|--------|--------|
| 1 Docker foundation | Done | SDK tools, logs/uptime/search, Rich tables |
| 2 LLM integration | Done | Ollama adapter, tool schemas, ask loop |
| 3 Interactive chat | Done | `dockai chat`, session focus |
| 4 Safe mutations | Done | start/stop/restart + confirm + verify |
| **5 Hardening** | **Done** | Acceptance tests, disposable Docker tests, timeouts, diagnostics, docs |

### Performance notes

Natural-language asks usually take seconds because of **LLM round-trips**, not Docker (`docker ps` is still fast). Prefer direct commands when you know the op. Mutation apply/verify runs in-app after confirm (no extra model hop). Spinners show stage (`Asking the model…` / `Fetching from Docker…`) plus `Completed in …`.

## Testing

```bash
# Unit + acceptance (mocked). Integration tests auto-skip if Docker is down.
pytest

# Only disposable-container integration tests (needs Docker; may pull alpine:3.20)
pytest -m integration
```

Acceptance IDs AT-01…AT-15 live in `tests/test_acceptance.py`. Integration tests create a unique `dockai-at-*` alpine container and remove it afterward — do not point them at production workloads.

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| `Docker Engine is unavailable` | Docker Desktop/daemon running; your user can access the socket |
| Slow NL answers (~10–20s) | Expected with local 8B models; use `dockai containers` for instant lists |
| Ollama errors | `ollama serve`, model pulled, `DOCKAI_MODEL` matches `ollama list` |
| Need tool traces | `dockai -v "…"` or `DOCKAI_DEBUG=1` |

## Safety

- LLM selects only predefined tools (no shell command execution).
- start/stop/restart **propose** only; the CLI requires explicit confirmation before apply.
- Facts (IDs, status, logs) come from Docker responses, not model invention.
- Restricted actions (delete/remove/prune, Docker Desktop control) are refused up front with a clear **Not supported** message — dockai will not silently substitute stop.
