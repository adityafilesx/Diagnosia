# Diagnosia: one FastAPI process that serves the API and web/. Works on any host that runs a
# container (Render, Railway, Fly.io, a VPS). Netlify can't run it. See docs/DEPLOY.md.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # The database and stored documents live on a persistent disk mounted at /data.
    DIAGNOSIA_DB=/data/diagnosia.db \
    DIAGNOSIA_DOCUMENTS=/data/documents \
    # Session cookies are HTTPS-only. The host's proxy ends TLS; browsers only open the
    # microphone on https, so DiagnoFast's voice needs it too.
    DIAGNOSIA_HTTPS=1 \
    # The host's proxy is the only thing that reaches the container, so its forwarded address is
    # trusted for rate limits. Narrow this to the proxy's address where the host publishes one.
    FORWARDED_ALLOW_IPS=*

WORKDIR /app
# The lock pins every package for Linux, and is what CI installs and audits.
COPY backend/requirements.lock backend/requirements.lock
RUN pip install -r backend/requirements.lock

COPY backend backend
COPY web web
RUN useradd --create-home --uid 10001 diagnosia \
    && mkdir -p /data \
    && chown diagnosia /data
USER diagnosia

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)"
# One worker: SQLite has one writer, and the reminder and delivery sweeps run inside the process.
CMD ["sh", "-c", "exec uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers"]
