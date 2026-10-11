# dockai

Natural-language Docker CLI agent. Phases 1–3 are in place; Phase 4 adds safe start/stop/restart with explicit confirmation.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Needs Docker Engine access. Natural-language modes need [Ollama](https://ollama.com) with a tool-capable model:

```bash
ollama pull llama3.1:8b
# optional: export DOCKAI_MODEL=llama3.1:8b
# optional: export OLLAMA_HOST=http://127.0.0.1:11434
```

## Commands

```bash
# Natural language (LLM + tools) — slower; most time is Ollama, not Docker
dockai "show running containers"
dockai ask "show the last 25 lines of api-server logs"
dockai "stop api-server"          # proposes action, asks to confirm, then applies

# Interactive session
dockai chat

# Direct tools (no LLM) — near docker CLI speed
dockai containers
dockai containers --all
dockai inspect <name-or-id>
dockai logs <name-or-id>              # last 100 lines
dockai logs <name-or-id> --tail 25
dockai logs <name-or-id> --full
dockai search flink
dockai uptime
dockai start <name-or-id>             # confirms, then starts
dockai stop <name-or-id>
dockai restart <name-or-id>
```

## Roadmap

| Phase | Status | Focus |
|-------|--------|--------|
| 1 Docker foundation | Done | SDK tools, logs/uptime/search, Rich tables |
| 2 LLM integration | Done | Ollama adapter, tool schemas, ask loop |
| 3 Interactive chat | Done | `dockai chat`, session focus for follow-ups |
| **4 Safe mutations** | **Current** | start/stop/restart + confirm + verify |
| 5 Hardening | Next | Acceptance tests, disposable containers, docs |

### Performance plan (query execution time)

Natural-language asks are slow mainly because of **two LLM round-trips** (choose tool → summarize). Docker itself is usually milliseconds.

Planned / preferred ways to cut latency:

1. **Prefer direct commands** for known ops (`dockai containers`, `dockai logs …`) — no model.
2. **Table-first replies** — after a successful read tool, print a Rich table and skip or shorten the summary LLM call.
3. **Faster / smaller Ollama model** via `DOCKAI_MODEL` when tool-calling quality allows.
4. **Fewer tool rounds** — coerce args, fuzzy names, and confirmation handled in-app (not by the model inventing JSON).
5. **Timed UX** — spinner + `Completed in …` so you can see where time goes (`Asking the model…` vs `Fetching from Docker…`).
6. **Mutations without a third LLM hop** — after confirm, apply + verify in-app and report Docker’s observed state.

Phase 5 will tighten this with diagnostics for per-stage timings.
