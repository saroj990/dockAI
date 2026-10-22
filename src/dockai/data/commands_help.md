# dockai commands

Use **dockai** for Docker on your machine. These are **dockai** commands — not raw `docker` CLI.

## Direct CLI

| Command | What it does |
|---------|----------------|
| `dockai containers` | List containers (running by default; `-a` for all) |
| `dockai uptime` | Uptime for running containers |
| `dockai logs <name>` | Tail logs for one container |
| `dockai inspect <name>` | Inspect one container |
| `dockai search <keyword>` | Search container names |
| `dockai start \| stop \| restart <name>` | Lifecycle (asks you to confirm) |
| `dockai config` | Show Ollama/Docker settings |
| `dockai setup config` | Interactive Ollama host + model setup |
| `dockai ask "<question>"` | One-shot natural language |
| `dockai chat` | Interactive session with follow-ups |

Bare prompts work too: `dockai "how many running containers?"`

## Natural language examples

- **List:** how many running containers? · show running containers · list exited containers
- **Logs:** logs for pg_tileserv · show me logs for api-server · last 50 lines of nginx logs
- **Inspect / search:** inspect timescaledb · find containers named redis
- **Uptime:** show uptime of containers
- **Diagnosis:** why is my container restarting? · troubleshoot logs for postgis
- **Lifecycle (confirmed):** stop api-server · restart pg_tileserv

## Tips

- Short, clear container **names** work best (e.g. `pg_tileserv`).
- Simple list/logs phrases often skip the LLM and run faster.
- Type `exit` to leave `dockai chat`.
