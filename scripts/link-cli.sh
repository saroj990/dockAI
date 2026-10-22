#!/usr/bin/env bash
# One-time: put `dockai` on your PATH for every new terminal (no venv activate).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/scripts/dockai"
BIN_DIR="${DOCKAI_BIN_DIR:-$HOME/.local/bin}"
LINK="$BIN_DIR/dockai"

if [[ ! -x "$LAUNCHER" ]]; then
  chmod +x "$LAUNCHER"
fi

# Ensure package works before linking.
"$LAUNCHER" --help >/dev/null

mkdir -p "$BIN_DIR"
ln -sfn "$LAUNCHER" "$LINK"
echo "→ Linked $LINK -> $LAUNCHER"

# shellcheck disable=SC2016
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
  SHELL_NAME="$(basename "${SHELL:-zsh}")"
  RC=""
  case "$SHELL_NAME" in
    zsh) RC="$HOME/.zshrc" ;;
    bash) RC="$HOME/.bashrc" ;;
    *) RC="$HOME/.profile" ;;
  esac
  LINE="export PATH=\"$BIN_DIR:\$PATH\""
  if [[ -f "$RC" ]] && grep -Fq "$BIN_DIR" "$RC" 2>/dev/null; then
    echo "→ $BIN_DIR already mentioned in $RC (open a new terminal if dockai is not found)"
  else
    echo "" >>"$RC"
    echo "# dockai CLI" >>"$RC"
    echo "$LINE" >>"$RC"
    echo "→ Added $BIN_DIR to PATH in $RC"
  fi
  echo
  echo "Run this once now (or open a new terminal):"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
else
  echo "→ $BIN_DIR is already on PATH"
fi

echo
echo "Then from any directory:"
echo "  dockai chat"
echo "  dockai containers"
