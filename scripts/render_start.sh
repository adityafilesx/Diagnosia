#!/usr/bin/env bash
# Render's start command for the judge-mode demo (docs/DEPLOY_RENDER.md).
# The free tier's disk is empty on every boot, so this rebuilds the made-up data, then serves.
set -euo pipefail
cd "$(dirname "$0")/.."

# The key ring arrives as a Render Secret File, which may be readable by others. deploy_boot copies it
# here, outside the repository, readable by this user only.
export DIAGNOSIA_DOCUMENT_KEY_FILE="${DIAGNOSIA_DOCUMENT_KEY_FILE:-$HOME/.diagnosia/document-keys.json}"

python -m backend.deploy_boot

# One worker: SQLite has one writer and the sweeps run in-process. Render's proxy is the only thing
# that reaches the service, so its forwarded address is trusted for the rate limits.
exec uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 \
    --proxy-headers --forwarded-allow-ips="*"
