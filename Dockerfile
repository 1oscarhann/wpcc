# Hearthforge in one image: the built frontend served by the API from the same origin (D-123).
#   docker build -t hearthforge .
#   docker run -p 8000:8000 -e DATABASE_URL=... hearthforge
# The same image runs the worker: `python -m hearthforge.worker` (see render.yaml).

# ── 1. the frontend ──────────────────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /app
COPY shared ./shared
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY frontend ./frontend
RUN cd frontend && npm run build

# ── 2. the server ────────────────────────────────────────────────────────────
FROM python:3.13-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY config ./config
COPY shared ./shared
RUN cd backend && uv sync --frozen --no-dev
COPY --from=web /app/frontend/dist ./static
ENV PATH="/app/backend/.venv/bin:$PATH" HF_ENV=prod HF_STATIC_DIR=/app/static HF_CONFIG_STRICT=true PORT=8000
WORKDIR /app/backend
EXPOSE 8000
# migrations first (idempotent), then one uvicorn process: rooms live in memory (PLAN §1.4)
CMD ["sh", "-c", "alembic upgrade head && uvicorn hearthforge.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
