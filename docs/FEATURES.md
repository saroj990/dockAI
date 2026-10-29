# dockai features

Natural-language and direct CLI for your **local Docker Engine**. Ollama is optional except for open-ended `ask` / `chat` turns that need the agent.

---

## Direct CLI (no LLM)

| Command | Purpose |
|--------|---------|
| `dockai containers` | List containers (running by default; `--all` for stopped/exited) |
| `dockai uptime` | Uptime for containers |
| `dockai logs <name>` | Tail logs (`-n`, `--full`) |
| `dockai inspect <name>` | Inspect one container |
| `dockai search <keyword>` | Search by name |
| `dockai start \| stop \| restart <name>` | Lifecycle — **confirm** before apply |
| `dockai config` | Show resolved Ollama/Docker settings |
| `dockai setup config` | Interactive save of Ollama host + model to TOML |
| `dockai --version`, `-v` / `--verbose` | Version; tool-call debug logs |
| `dockai --config <path>` | Alternate config file |

One-shot NL without chat:

```bash
dockai ask "show running containers"
dockai "show running containers"
dockai ask --model qwen2.5:3b "list uptime"
```

---

## Natural language (`ask`, `chat`)

### Fast paths (local intent → Docker, often no LLM)

Timings show `shortcut:…` instead of `ollama #1`.

- **List / filter:** running, exited, stopped, all containers
- **Columns:** “only name and uptime”, custom column sets on tables
- **Logs:** “logs for pg_tileserv”, “last 25 lines of …”
- **Inspect, search, uptime** phrasing
- **Lifecycle NL:** “stop api-server” (still confirmed)
- **Diagnose shortcut:** restart / crash / “showing issues” → `troubleshoot_container_logs` (inspect + log scan + fact-first answer)
- **Fuzzy names:** typos like `pg tilserv` → `pg_tileserv` (session focus or live Docker names)

Politeness and filler (“please”, “show me”, “can we see”) are stripped before matching.

### LLM paths (Ollama)

| Path | When | Timing label |
|------|------|----------------|
| **Casual chat** | hello, thanks, how are you — no tool schemas | `ollama (chat)` |
| **Tool agent** | Vague or complex Docker asks | `ollama #1`, `#2`, … |
| **Diagnosis (non-shortcut)** | Must call `troubleshoot_container_logs` before claims; may add LLM summary after facts | `ollama #N` + `docker troubleshoot_container_logs` |
| **Meta help** | “what commands can I run?” | No Ollama (markdown help) |
| **Proposed exec** | Model suggests `docker exec`; you confirm | Same as lifecycle |

### Interactive chat

- Follow-ups in one session
- **Focused container** for “its logs”, “is it restarting”, etc.
- Confirm start / stop / restart / exec in-session

---

## Troubleshooting (`troubleshoot_container_logs`)

Used for diagnosis asks (shortcut or LLM-triggered).

1. **Inspect** — status, restarts, `Restarting`, health, uptime, exit code, OOM
2. **Logs** — default last **150 lines**
3. **Signal scan** — FATAL, ERROR, OOM, panic, connection refused, tracebacks, permission denied (highlights only; no invented lines)
4. **UI** — Rich troubleshoot table + log signal lines
5. **Answer** — fact-first text: inspect bullets, restart-loop vs your question, log scan summary

Often **skips a second LLM call** when you asked about restarting but Docker shows no active loop.

Plain log tailing without diagnosis uses `dockai logs` or the logs shortcut (`get_container_logs`).

---

## Ollama integration

- **`[ollama]`** in `dockai.toml`: `host`, `model`, `timeout`, `health_timeout`, optional `fallback_host`, `fallback_model`
- Env overrides: `OLLAMA_HOST`, `DOCKAI_MODEL`, `DOCKAI_OLLAMA_*`
- **Remote Ollama** with optional **local fallback** when primary is unreachable
- **Preflight** (`/api/tags`, capped ~5s) before `ask` / `chat` with spinner (“Pinging remote…”, “Pinging local model…”)
- Tool-calling models for the full agent path (`qwen2.5:3b`, `llama3.1:8b`, etc.)

Docker always uses **your local** Engine unless you change the socket separately.

---

## Configuration

- Search order: `DOCKAI_CONFIG` → `./dockai.toml` → `~/.config/dockai/config.toml`
- Precedence: CLI flags > env > file > defaults
- `dockai config` prints resolved values

---

## Name resolution

| Input | Behavior |
|-------|----------|
| `saien-backend-api` | Exact |
| `saien backend api` | Normalized (ignore spaces/hyphens) |
| Close typo | One clear match → use it |
| Several close matches | Ambiguous — list; no auto-pick |
| Hex-like ID | Exact ID only — never fuzzy to a name |

---

## Safety and restrictions

- Fixed **tool registry** only — no shell execution of model output
- **start / stop / restart / exec** require explicit confirmation
- Facts from **Docker tools**, not model invention; fake tool JSON is rejected on diagnosis asks
- **Not supported:** delete/remove containers, prune, image/volume delete, quitting Docker Desktop

When the daemon is down: clear **“Docker is not running”** message (no traceback).

---

## Performance (typical)

| Path | Speed | Indicator |
|------|--------|-----------|
| Direct CLI | ~`docker ps` | No Ollama line in timings |
| NL shortcut | ~100–300 ms + Docker | `shortcut:list`, `shortcut:logs`, `shortcut:diagnose`, … |
| Table-first after tool | One LLM call if any | Skips second summary for list/logs/inspect |
| Casual greeting | Faster LLM | `ollama (chat)`, no tools in request |
| Full agent / diagnosis | Seconds | Multiple `ollama #N` lines |

---

## Related docs

- [README](../README.md) — install, smoke tests, examples
- [commands_help.md](../src/dockai/data/commands_help.md) — in-app “what can I run?” text
- [dockai.example.toml](../dockai.example.toml) — sample config
