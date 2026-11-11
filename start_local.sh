#!/usr/bin/env bash
# One command to run Diagnosia locally with test accounts, on macOS or Linux.
#   ./start_local.sh            # then open http://127.0.0.1:8000/login.html
#   ./start_local.sh --port 8001
# Uses a .venv with Python 3.11+ and pip. A missing, old or broken .venv is set aside
# (renamed, never deleted) and a fresh one is made. Then it installs the requirements,
# seeds the synthetic accounts if they are missing, and starts the server.
set -euo pipefail
cd "$(dirname "$0")"

pick_python() {
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

venv_works() {
  [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys, pip; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

if ! venv_works && [ -x .venv/bin/python ]; then
  # A venv with no pip can often be repaired in place.
  .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
fi

if ! venv_works; then
  PYTHON="$(pick_python)" || { echo "Python 3.11 or newer is needed. On a Mac: brew install python@3.11" >&2; exit 1; }
  if [ -e .venv ]; then
    ASIDE=".venv.broken-$(date +%Y%m%d%H%M%S)"
    echo "The existing .venv is missing pip or is too old. Moving it to $ASIDE and making a new one."
    mv .venv "$ASIDE"
  fi
  "$PYTHON" -m venv .venv
fi

.venv/bin/python -m pip install -q -r backend/requirements.txt
exec .venv/bin/python -m backend.synthetic.serve "$@"
