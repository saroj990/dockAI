# dockai

Natural-language Docker CLI agent.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Needs Docker Engine access. Phase 2 also needs [Ollama](https://ollama.com) with a tool-capable model:

```bash
ollama pull llama3.1:8b
# optional: export DOCKAI_MODEL=llama3.1:8b
# optional: export OLLAMA_HOST=http://127.0.0.1:11434
```

## Commands

```bash
# Phase 2 — natural language (Ollama tool calling)
dockai "show running containers"
dockai ask "show the last 25 lines of api-server logs"

# Phase 3 — interactive session with follow-ups
dockai chat
# You: show containers that are restarting
# You: show its recent logs


# Phase 1 — direct tools (no LLM)
dockai containers
dockai containers --all
dockai inspect <name-or-id>
dockai logs <name-or-id>              # last 100 lines
dockai logs <name-or-id> --tail 25
dockai logs <name-or-id> --full
dockai search flink
dockai uptime
```
