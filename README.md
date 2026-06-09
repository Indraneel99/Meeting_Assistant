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

Tool providers default to local stubs for offline development. Configure real integrations per tool:

```bash
# Email via SendGrid
export MEETING_ASSISTANT_EMAIL_PROVIDER="sendgrid"
export MEETING_ASSISTANT_EMAIL_SENDGRID_API_KEY="..."
export MEETING_ASSISTANT_EMAIL_FROM_ADDRESS="noreply@yourdomain.com"
export MEETING_ASSISTANT_EMAIL_DEFAULT_RECIPIENT="team@yourdomain.com"

# Calendar via Google service account (requires: uv sync --extra tools)
export MEETING_ASSISTANT_CALENDAR_PROVIDER="google"
export MEETING_ASSISTANT_CALENDAR_GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export MEETING_ASSISTANT_CALENDAR_GOOGLE_CALENDAR_ID="primary"

# Slack via incoming webhook or bot token
export MEETING_ASSISTANT_SLACK_PROVIDER="webhook"
export MEETING_ASSISTANT_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Jira REST API
export MEETING_ASSISTANT_JIRA_PROVIDER="rest"
export MEETING_ASSISTANT_JIRA_BASE_URL="https://your-org.atlassian.net"
export MEETING_ASSISTANT_JIRA_USER_EMAIL="bot@yourdomain.com"
export MEETING_ASSISTANT_JIRA_API_TOKEN="..."
export MEETING_ASSISTANT_JIRA_PROJECT_KEY="ENG"
```

Retry backoff can run off the request thread when using async workers:

```bash
export MEETING_ASSISTANT_TOOL_EXECUTION_BACKOFF_MODE="background"
```

## Test

```bash
uv run pytest
```
