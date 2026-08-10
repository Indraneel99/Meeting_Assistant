# Meeting Assistant

This repository contains a batch-first meeting assistant scaffold that follows a production-shaped architecture while staying simple enough to iterate locally.

## What is included

- FastAPI service for batch meeting ingestion and retrieval
- Durable workflow state in Postgres-compatible SQLAlchemy models
- Queue, hybrid ASR, planner, tool execution, and embedding abstractions
- Read-oriented retrieval endpoints that mirror the future real-time query service
- Lightweight tests for the API and orchestration flow

## Architecture notes

The current implementation is a modular monolith:

- Batch ingestion enters through the API
- Transcript text can be provided directly, or audio files can be transcribed through a hosted OpenAI batch ASR adapter
- Planning can run through a hosted OpenAI LLM with structured outputs, while keeping a local heuristic fallback for development
- ASR, normalization, and chunking feed an internal queue abstraction
- An orchestration service now runs a bounded agent loop with persisted step history, loop guards, and approval-aware pauses
- Tool execution now includes idempotency keys, retry attempts, approval gating for calendar actions, and dead-letter style failure metadata
- Retrieval endpoints expose recent memory, tasks, and decisions

The storage model is compatible with a future Postgres + pgvector deployment. Local development defaults to SQLite, while the vector layer is abstracted so a real pgvector-backed implementation can replace the in-process cosine similarity store.

## User integrations (Phase 13 — planned)

v1 uses **deploy-level** tool credentials (one Slack webhook, SendGrid sender, Google service account for the whole deployment). The multi-user product moves to **per-user connections** with **Meeting Assistant app identity** for outbound actions:

| Channel | User connects | Messages appear as |
|---------|---------------|-------------------|
| Slack | Workspace OAuth + channel picker | **Meeting Assistant** bot (not the user) |
| Email | Notification email preferences | **Meeting Assistant** branded sender via SendGrid |
| Calendar | Optional Google read; writes via assistant calendar | Invite from **Meeting Assistant** calendar |

Users authorize the app; the app acts with its own visible identity (similar to GitHub Apps / Cursor bot commits). See [`ARCHITECTURE.md`](./ARCHITECTURE.md) ADR-15 and [`features.json`](./features.json) Phase 13 features.

## Frontend

A Vite + React app lives in [`frontend/`](./frontend/). Run the API on port 8000, then `cd frontend && npm run dev` for port 5173. Planned: **Settings → Integrations** for connect/disconnect flows.

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

Production-style async processing uses Redis + ARQ:

```bash
export MEETING_ASSISTANT_BATCH_PROCESSING_MODE="async"
export MEETING_ASSISTANT_JOB_QUEUE_PROVIDER="arq"
export MEETING_ASSISTANT_QUEUE_PROVIDER="redis"
export MEETING_ASSISTANT_REDIS_URL="redis://localhost:6379/0"
uv run arq meeting_assistant.worker.WorkerSettings
```

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

Tool providers default to local stubs for offline development. **v1:** configure one set of credentials per deployment via env vars. **Phase 13:** per-user integrations replace deploy-level Slack/webhook routing; email uses deploy SendGrid with per-user recipient prefs.

```bash
# --- v1 deploy-level (single-tenant GCP today) ---

# Email via SendGrid (Meeting Assistant branded sender)
export MEETING_ASSISTANT_EMAIL_PROVIDER="sendgrid"
export MEETING_ASSISTANT_EMAIL_SENDGRID_API_KEY="..."
export MEETING_ASSISTANT_EMAIL_FROM_ADDRESS="Meeting Assistant <notifications@yourdomain.com>"
export MEETING_ASSISTANT_EMAIL_DEFAULT_RECIPIENT="team@yourdomain.com"

# Calendar via Google service account (Phase 13: assistant-owned organizer calendar)
export MEETING_ASSISTANT_CALENDAR_PROVIDER="google"
export MEETING_ASSISTANT_CALENDAR_GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export MEETING_ASSISTANT_CALENDAR_GOOGLE_CALENDAR_ID="primary"

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

Phase 13 OAuth app credentials (Slack client_id/secret, Google OAuth client) will be documented in `.env.production.example` when implemented. See `ARCHITECTURE.md` for the integrations API surface.

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

Auth is disabled by default for local development. Enable API key or JWT protection on `/api/v1/*` and `/admin/*`:

```bash
export MEETING_ASSISTANT_AUTH_ENABLED="true"
export MEETING_ASSISTANT_AUTH_MODE="api_key"
export MEETING_ASSISTANT_AUTH_API_KEYS="alice:your-secret-key,service-admin:admin-key"
```

Scoped keys use `user_external_id:api_key`. Keys without a prefix can access any user. JWT mode:

```bash
export MEETING_ASSISTANT_AUTH_MODE="jwt"
export MEETING_ASSISTANT_AUTH_JWT_SECRET="your-32-byte-minimum-secret"
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
