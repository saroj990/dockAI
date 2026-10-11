# dockai

Natural-language Docker CLI agent. Phase 1 provides a typed CLI over the Docker SDK for read-only container inspection.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requires a local Docker Engine the current user can access.

## Phase 1 commands

```bash
dockai containers                     # running containers
dockai containers --all               # all containers
dockai inspect <name-or-id>
dockai logs <name-or-id>              # last 100 lines
dockai logs <name-or-id> --tail 25
dockai logs <name-or-id> --full
dockai search flink                   # keyword search (all containers)
dockai search flink --running-only
dockai uptime                         # uptime / state table
```

Later phases add LLM tool calling, chat, and confirmed start/stop/restart.
