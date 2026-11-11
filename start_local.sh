#!/usr/bin/env bash
# One command to run Diagnosia locally with test accounts, on macOS or Linux.
#   ./start_local.sh            # then open http://127.0.0.1:8000/login.html
#   ./start_local.sh --port 8001
# Makes a .venv with Python 3.11+ on first run, installs the requirements, seeds the
# synthetic accounts if they are missing, and starts the server.
set -euo pipefail
cd "$(dirname "$0")"

pick_python() {
  for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

if [ ! -x .venv/bin/python ]; then
  PYTHON="$(pick_python)" || { echo "Python 3.11 or newer is needed. On a Mac: brew install python@3.11" >&2; exit 1; }
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install -q -r backend/requirements.txt
exec .venv/bin/python -m backend.synthetic.serve "$@"
