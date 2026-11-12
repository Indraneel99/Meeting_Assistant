# Meeting Assistant

This repository contains a batch-first meeting assistant with a production-shaped modular monolith architecture and a Vite+React frontend.

## What is included

- FastAPI service for batch meeting ingestion, agent tool execution, and retrieval
- Durable workflow state in Postgres-compatible SQLAlchemy models (SQLite for local dev)
- Queue, hybrid ASR, planner, tool execution, and embedding abstractions
- Per-user integrations (Slack, email prefs, Google calendar) with OAuth connect API
- Vite+React frontend: upload, workflow status, search, RAG query, approvals, integrations settings, email/password and Google login
- 210+ pytest tests; CI with ruff, mypy, SQLite suite, and Postgres migration smoke

## Architecture notes

The current implementation is a modular monolith:

- Batch ingestion enters through the API
- Transcript text can be provided directly, or audio files can be transcribed through a hosted OpenAI batch ASR adapter
- Planning can run through a hosted OpenAI LLM with structured outputs, while keeping a local heuristic fallback for development
- ASR, normalization, and chunking feed an internal queue abstraction
- An orchestration service now runs a bounded agent loop with persisted step history, loop guards, and approval-aware pauses
- Tool execution now includes idempotency keys, retry attempts, approval gating for calendar actions, and dead-letter style failure metadata
- Retrieval endpoints expose recent memory, tasks, and decisions

Local development defaults to SQLite and an in-process vector store. Production uses Cloud SQL Postgres with pgvector: semantic search reads stored `summary_embedding` vectors. The vector layer stays behind an abstraction so local runs do not need Postgres.

## User integrations (Phase 13 — complete)

v1 **deploy-level** tool credentials (one Slack webhook, SendGrid sender, Google service account) remain as org fallback. Multi-user product uses **per-user connections** with **Meeting Assistant app identity** for outbound actions:

| Channel | User connects | Messages appear as |
|---------|---------------|-------------------|
| Slack | Workspace OAuth + channel picker | **Meeting Assistant** bot (not the user) |
| Email | Notification email preferences | **Meeting Assistant** branded sender via SendGrid |
| Calendar | Optional Google read; writes via assistant calendar | Invite from **Meeting Assistant** calendar |

Configure OAuth app credentials in `.env.production.example` (`SLACK_OAUTH_*`, `GOOGLE_OAUTH_*`, `INTEGRATIONS_ENCRYPTION_KEY`). Users manage connections in **Settings → Integrations** in the frontend. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) ADR-15 and [`features.json`](./features.json) `integrations-*` features.

## Frontend

A Vite + React app lives in [`frontend/`](./frontend/). Run the API on port 8000, then `cd frontend && npm run dev` for port 5173. Screens: Upload, Workflow status, Search, Ask (RAG), Approvals, **Settings → Integrations**, and `/login` / `/register`.

Browser auth is email/password or Sign in with Google (`POST /api/v1/auth/register`, `POST /api/v1/auth/login/email`, `GET /api/v1/auth/google/connect`). The app stores a JWT and sends `Authorization: Bearer`. `X-API-Key` and `POST /api/v1/auth/login` remain for Postman and scripts only. See [`progress.md`](./progress.md) Phase 15 and ADR-17 in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Run locally

```bash
uv sync
uv run uvicorn meeting_assistant.main:app --reload
```

The app applies Alembic migrations on startup. SQLite remains the default for local development:

```bash
export MEETING_ASSISTANT_DATABASE_URL="sqlite:///./meeting_assistant.db"
```

For Postgres, install/create the database externally and point the app at it:

```bash
export MEETING_ASSISTANT_DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/meeting_assistant"
export MEETING_ASSISTANT_DATABASE_POOL_SIZE="5"
export MEETING_ASSISTANT_DATABASE_MAX_OVERFLOW="10"
uv run alembic upgrade head
```

Embeddings default to the local heuristic embedder for offline development. On Postgres, semantic search uses stored `summary_embedding` vectors with pgvector. To enable hosted embeddings:

```bash
export MEETING_ASSISTANT_EMBEDDING_PROVIDER="openai"
export MEETING_ASSISTANT_EMBEDDING_OPENAI_API_KEY="..."
export MEETING_ASSISTANT_EMBEDDING_OPENAI_MODEL="text-embedding-3-small"
```

Async batch processing returns `202 Accepted` with a workflow job id. Local development can run jobs in-process:

```bash
export MEETING_ASSISTANT_BATCH_PROCESSING_MODE="async"
export MEETING_ASSISTANT_JOB_QUEUE_PROVIDER="inprocess"
```

Docker Compose and a local production-shaped worker use Redis + ARQ:

```bash
export MEETING_ASSISTANT_BATCH_PROCESSING_MODE="async"
export MEETING_ASSISTANT_JOB_QUEUE_PROVIDER="arq"
export MEETING_ASSISTANT_QUEUE_PROVIDER="redis"
export MEETING_ASSISTANT_REDIS_URL="redis://localhost:6379/0"
uv run arq meeting_assistant.worker.WorkerSettings
```

GCP production uses Pub/Sub. The API publishes batch jobs, and Cloud Run pushes them to the worker at `POST /internal/jobs/batch`. Redis stays in use for approval locks.

```bash
export MEETING_ASSISTANT_BATCH_PROCESSING_MODE="async"
export MEETING_ASSISTANT_JOB_QUEUE_PROVIDER="pubsub"
export MEETING_ASSISTANT_PUBSUB_TOPIC="meeting-assistant-batch-jobs"
export MEETING_ASSISTANT_PUBSUB_PROJECT="your_project_id"
```

Deploy wiring lives in `deploy/.env.prod` (`make deploy-api`, `make deploy-worker`). See [`progress.md`](./progress.md) Phase 14.

### Docker Compose (Postgres + Redis + API + worker)

Production-shaped local stack without GCP:

```bash
cp .env.compose.example .env.compose
make compose-up
make compose-smoke   # /health + /ready on :8000, worker :8081
```

API docs: http://127.0.0.1:8000/docs. Stop with `make compose-down`.

Poll workflow status with `GET /api/v1/workflows/{workflow_run_id}`.

Approval requests for gated calendar actions can be listed and resolved:

```bash
# List pending approvals for a workflow
curl http://127.0.0.1:8000/api/v1/workflows/{workflow_run_id}/approvals

# Approve or reject
curl -X POST http://127.0.0.1:8000/api/v1/approvals/{approval_request_id}/approve \
  -H "Content-Type: application/json" \
  -d '{"resolved_by": "alice"}'

curl -X POST http://127.0.0.1:8000/api/v1/approvals/{approval_request_id}/reject \
  -H "Content-Type: application/json" \
  -d '{"resolved_by": "alice"}'
```

A minimal admin UI is available at `GET /admin/approvals/{approval_request_id}`.

To enable hosted batch ASR for `source_uri` inputs, set:

```bash
export MEETING_ASSISTANT_ASR_OPENAI_API_KEY="..."
export MEETING_ASSISTANT_ASR_PROVIDER="openai"
```

Upload audio directly via multipart form:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meetings/batch/upload \
  -F user_external_id=alice \
  -F user_email=alice@example.com \
  -F title="Weekly sync" \
  -F audio=@meeting.wav
```

Audio uploads are stored locally by default (`./uploads/audio`) and referenced as `file://` URIs for ASR. For S3-backed uploads:

```bash
export MEETING_ASSISTANT_ASR_UPLOAD_BACKEND="s3"
export MEETING_ASSISTANT_ASR_S3_BUCKET="my-bucket"
export MEETING_ASSISTANT_ASR_S3_REGION="us-east-1"
```

ASR can also read audio from object storage URIs:

- `s3://bucket/path/to/meeting.wav` (requires AWS credentials via standard boto3 env/instance profile)
- `gs://bucket/path/to/meeting.wav` (requires `google-cloud-storage` and GCP credentials)

Optional:

```bash
export MEETING_ASSISTANT_ASR_OPENAI_MODEL="gpt-4o-transcribe-diarize"
export MEETING_ASSISTANT_ASR_OPENAI_LANGUAGE="en"
```

To enable hosted planning with structured outputs, set:

```bash
export MEETING_ASSISTANT_LLM_OPENAI_API_KEY="..."
```

Optional:

```bash
export MEETING_ASSISTANT_LLM_OPENAI_MODEL="gpt-5.4-mini"
export MEETING_ASSISTANT_LLM_PROVIDER="openai"
```

If no LLM API key is configured, the app falls back to the local heuristic planner so you can keep testing offline.

Tool providers default to local stubs for offline development. **Deploy-level** credentials work as org fallback; **per-user integrations** (Phase 13) resolve channels/recipients via `UserToolProviderFactory` when users connect in Settings → Integrations.

```bash
# --- v1 deploy-level (single-tenant GCP today) ---

# Email via SendGrid (Meeting Assistant branded sender)
export MEETING_ASSISTANT_EMAIL_PROVIDER="sendgrid"
export MEETING_ASSISTANT_EMAIL_SENDGRID_API_KEY="..."
export MEETING_ASSISTANT_EMAIL_FROM_ADDRESS="notifications@yourdomain.com"
export MEETING_ASSISTANT_EMAIL_FROM_NAME="Meeting Assistant"
export MEETING_ASSISTANT_EMAIL_DEFAULT_RECIPIENT="team@yourdomain.com"

# Calendar via Google service account (assistant-owned organizer calendar)
# Impersonate a Workspace user that has Calendar turned on. Domain-wide delegation
# scope: https://www.googleapis.com/auth/calendar
export MEETING_ASSISTANT_CALENDAR_PROVIDER="google"
export MEETING_ASSISTANT_CALENDAR_GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export MEETING_ASSISTANT_CALENDAR_GOOGLE_CALENDAR_ID="assistant@yourdomain.com"
export MEETING_ASSISTANT_CALENDAR_GOOGLE_IMPERSONATE_SUBJECT="assistant@yourdomain.com"

# Slack via bot or webhook (Phase 13: per-user workspace OAuth, bot posts as Meeting Assistant)
export MEETING_ASSISTANT_SLACK_PROVIDER="webhook"
export MEETING_ASSISTANT_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Jira REST API (deferred)
export MEETING_ASSISTANT_JIRA_PROVIDER="rest"
export MEETING_ASSISTANT_JIRA_BASE_URL="https://your-org.atlassian.net"
export MEETING_ASSISTANT_JIRA_USER_EMAIL="bot@yourdomain.com"
export MEETING_ASSISTANT_JIRA_API_TOKEN="..."
export MEETING_ASSISTANT_JIRA_PROJECT_KEY="ENG"
```

Phase 13 OAuth app credentials (Slack `SLACK_OAUTH_*`, Google `GOOGLE_OAUTH_*`, `INTEGRATIONS_ENCRYPTION_KEY`) are documented in `.env.production.example`. See `ARCHITECTURE.md` for the integrations API surface.

Retrieval uses semantic search across meeting summaries, transcript chunks, and decisions. `/query` synthesizes answers with citations from retrieved context. Enable hosted Q&A with:

```bash
export MEETING_ASSISTANT_QUERY_PROVIDER="openai"
export MEETING_ASSISTANT_LLM_OPENAI_API_KEY="..."
export MEETING_ASSISTANT_QUERY_TOP_K_CHUNKS="5"
```

Chunk search is available at `GET /api/v1/meetings/chunks/search`. Search and decisions endpoints support cursor pagination via `cursor` and return `next_cursor` / `has_more`.

Retry backoff can run off the request thread when using async workers:

```bash
export MEETING_ASSISTANT_TOOL_EXECUTION_BACKOFF_MODE="background"
```

### Production hardening

Auth is disabled by default for local development. Production uses JWT (`Authorization: Bearer`) from email/password or Google login (Phase 15). **API keys** remain for Postman/scripts only — stored in Secret Manager, not shown in the browser UI.

```bash
export MEETING_ASSISTANT_AUTH_ENABLED="true"
export MEETING_ASSISTANT_AUTH_JWT_SECRET="your-32-byte-minimum-secret"
export MEETING_ASSISTANT_AUTH_PASSWORD_LOGIN_ENABLED="true"
export MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_ENABLED="true"
```

Ops / M2M (optional — not for end-user browser login):

```bash
export MEETING_ASSISTANT_AUTH_MODE="api_key"
export MEETING_ASSISTANT_AUTH_API_KEYS="service-admin:admin-key"
```

Operational endpoints:

```bash
curl http://127.0.0.1:8000/health   # liveness
curl http://127.0.0.1:8000/ready    # database/redis/embedder readiness
```

Optional observability and rate limits:

```bash
export MEETING_ASSISTANT_LOG_JSON="true"
export MEETING_ASSISTANT_OTEL_ENABLED="true"
export MEETING_ASSISTANT_OTEL_EXPORTER_ENDPOINT="http://localhost:4318/v1/traces"
export MEETING_ASSISTANT_RATE_LIMIT_ENABLED="true"
```

## Test

```bash
uv sync --extra dev
uv run ruff check src tests
uv run mypy src/meeting_assistant
uv run pytest
```
