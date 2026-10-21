#!/usr/bin/env bash
# One-time local setup for dockai: Python 3.11+ venv, install, verify CLI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EDITABLE=0
WITH_DEV=1
for arg in "$@"; do
  case "$arg" in
    --editable|-e) EDITABLE=1 ;;
    --no-dev) WITH_DEV=0 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/setup.sh [--editable] [--no-dev]

  Creates .venv (Python 3.11+), upgrades pip, installs dockai, verifies import + CLI.

  --editable   Install in editable mode (for local development)
  --no-dev     Skip optional pytest / [dev] extras
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

pick_python() {
  local candidates=(python3.13 python3.12 python3.11 python3)
  local cmd
  for cmd in "${candidates[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

if ! PYTHON="$(pick_python)"; then
  cat >&2 <<'EOF'
error: need Python 3.11 or newer on PATH.

  macOS (Homebrew):  brew install python@3.12
  Then re-run:        ./scripts/setup.sh
EOF
  exit 1
fi

PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
echo "→ Using $PYTHON ($PY_VER)"

if [[ ! -d .venv ]]; then
  echo "→ Creating virtualenv .venv"
  "$PYTHON" -m venv .venv
else
  # Recreate if existing venv is too old (e.g. system 3.9)
  if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    OLD="$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo unknown)"
    echo "→ Existing .venv is Python $OLD (< 3.11); recreating"
    rm -rf .venv
    "$PYTHON" -m venv .venv
  else
    echo "→ Reusing .venv"
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Upgrading pip / setuptools / wheel"
python -m pip install --upgrade pip setuptools wheel

EXTRAS=""
if [[ "$WITH_DEV" -eq 1 ]]; then
  EXTRAS="[dev]"
fi

if [[ "$EDITABLE" -eq 1 ]]; then
  echo "→ Installing dockai${EXTRAS} (editable)"
  pip install -e ".${EXTRAS}"
else
  # Regular install avoids hatchling/setuptools editable .pth edge cases.
  echo "→ Installing dockai${EXTRAS}"
  pip install ".${EXTRAS}"
fi

echo "→ Verifying import and CLI"
python -c 'import dockai; print("  import ok:", dockai.__file__)'
if ! command -v dockai >/dev/null 2>&1; then
  echo "error: dockai not on PATH after install (is .venv activated?)" >&2
  exit 1
fi
dockai --help >/dev/null
echo "  CLI ok: $(command -v dockai)"

if [[ ! -f dockai.toml && -f dockai.example.toml ]]; then
  cp dockai.example.toml dockai.toml
  echo "→ Wrote dockai.toml from dockai.example.toml (edit host/model as needed)"
fi

cat <<EOF

Setup complete.

Next (every new terminal):
  cd $ROOT
  source .venv/bin/activate
  dockai containers

Optional NL mode: install Ollama, pull a tool-capable model, then:
  dockai setup config
  # or edit dockai.toml / set OLLAMA_HOST
EOF
