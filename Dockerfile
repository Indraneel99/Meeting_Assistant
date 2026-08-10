# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Production runtime: core deps + GCS for gs:// ASR sources.
RUN uv sync --frozen --no-dev --extra storage --extra tools

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN useradd --create-home --shell /bin/bash appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser pyproject.toml uv.lock README.md alembic.ini ./
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser scripts/cloudrun_worker_entrypoint.sh ./scripts/cloudrun_worker_entrypoint.sh

RUN chmod +x ./scripts/cloudrun_worker_entrypoint.sh

USER appuser

EXPOSE 8080

# Default: API. Override on the worker Cloud Run service (see Makefile).
CMD ["sh", "-c", "exec uvicorn meeting_assistant.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
