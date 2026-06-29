#!/usr/bin/env bash
#
# Magpie one-shot setup.
#
# Creates a virtualenv, installs Magpie and its dependencies, prepares .env,
# and ensures a local Ollama model is available. Safe to re-run (idempotent).
#
# Usage:
#   ./setup.sh            # set up only
#   ./setup.sh serve      # set up, then launch the web UI
#   ./setup.sh demo       # set up, then run the end-to-end demo
#   ./setup.sh init       # set up, then run interactive onboarding
#
set -euo pipefail

# Always operate from the script's directory.
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"
MODEL="${OLLAMA_MODEL:-llama3.1}"

info()  { printf '\033[36m▸ %s\033[0m\n' "$1"; }
ok()    { printf '\033[32m✓ %s\033[0m\n' "$1"; }
warn()  { printf '\033[33m! %s\033[0m\n' "$1"; }

# 1. Python check
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3 not found. Install Python 3.11+ and retry." >&2
  exit 1
fi
ok "Using $($PYTHON --version)"

# 2. Virtualenv
if [ ! -d "$VENV" ]; then
  info "Creating virtualenv ($VENV)"
  "$PYTHON" -m venv "$VENV"
else
  ok "Virtualenv already exists"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 3. Dependencies (installs the `magpie` command too)
info "Installing dependencies (this may take a few minutes on first run)"
python -m pip install --quiet --upgrade pip
pip install --quiet -e .
ok "Dependencies installed"

# 4. Config
if [ ! -f ".env" ]; then
  cp .env.example .env
  ok "Created .env from .env.example"
else
  ok ".env already present"
fi

# 5. Ollama (local LLM)
if command -v ollama >/dev/null 2>&1; then
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    warn "Ollama is installed but not running. Start it with: ollama serve"
  elif curl -sf http://localhost:11434/api/tags | grep -q "\"${MODEL}"; then
    ok "Ollama model '${MODEL}' available"
  else
    info "Pulling Ollama model '${MODEL}'"
    ollama pull "$MODEL"
    ok "Model '${MODEL}' pulled"
  fi
else
  warn "Ollama not found. Install it from https://ollama.com/download, then run: ollama pull ${MODEL}"
fi

echo
ok "Setup complete."
echo "Activate the environment with:  source ${VENV}/bin/activate"
echo "Then try:  magpie serve   |   magpie init   |   python scripts/demo.py"
echo

# 6. Action — explicit argument wins; otherwise offer to launch the web UI.
case "${1:-}" in
  serve) info "Launching web UI…";     exec magpie serve ;;
  demo)  info "Running demo…";          exec python scripts/demo.py ;;
  init)  info "Starting onboarding…";   exec magpie init ;;
  "")
    if [ -t 0 ]; then
      read -r -p "Launch the web UI now? [Y/n] " reply
      case "$reply" in
        [Nn]*) echo "Skipped. Run 'magpie serve' when ready." ;;
        *)     info "Launching web UI at http://127.0.0.1:${MAGPIE_PORT:-8077} (Ctrl+C to stop)…"
               exec magpie serve ;;
      esac
    else
      echo "Run './setup.sh serve' (or 'magpie serve') to start the web UI."
    fi
    ;;
  *)     warn "Unknown argument '${1}'. Use: serve | demo | init" ;;
esac
