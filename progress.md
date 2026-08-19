# Meeting Assistant — Progress & Roadmap

Last updated: 2026-08-19

## Executive summary

Meeting Assistant is a **modular monolith** FastAPI backend with a Vite+React frontend. The full batch ingestion → agent → retrieval loop is **deployed on GCP (Cloud Run)** and verified end-to-end: batch ingestion, per-user tool integrations, workflow polling, semantic search, RAG query, and calendar approvals.

**62 of 64 features pass** in [`features.json`](./features.json). Remaining work:

1. **Phase 14 Pub/Sub worker** — complete ✅ (`deploy-pubsub-gcp`, `job-queue-pubsub`, `worker-pubsub-push`, `ops-pubsub-readiness`).
2. **Jira live integration** — deferred (`tool-jira-live`); wiring exists but is commented out in deploy config.
3. **Real-time ASR streaming** — v2 candidate (`realtime-asr-streaming`); different product surface from batch-first v1.

Use [`features.json`](./features.json) as the machine-readable source of truth. Update it when a feature is verified (`status: "pass"`, `evidence`, `testedAt`).

---

## Current state (verified)

| Area | Status | Notes |
|------|--------|-------|
| GCP API (Cloud Run) | ✅ Deployed | Batch, search, query, workflows, integrations |
| GCP Worker (Pub/Sub push) | ✅ Deployed | Scale-to-zero; push → `POST /internal/jobs/batch` (Phase 14 complete) |
| Cloud SQL Postgres | ✅ Running | pgvector migrations applied on startup |
| Redis / ARQ | ✅ Optional | Upstash still used for approval locks; job dispatch via Pub/Sub on GCP |
| OpenAI (LLM, embed, ASR, query) | ✅ Configured | Production env in `.env.production.example` |
| GCS audio storage | ✅ Configured | Upload + ASR source reads |
| Agent loop | ✅ Verified | Plan → tool execute → complete meeting; DB updated |
| Tool integrations | ✅ Live | Slack/SendGrid/Calendar on GCP; per-user OAuth + deploy fallback |
| Auth | ✅ Enabled | Scoped `X-API-Key` + JWT login; frontend Sign in panel |
| Frontend | ✅ Complete | Upload, workflow, search, query, approvals, Settings → Integrations |
| User integrations | ✅ Phase 13 | Schema, OAuth API, Settings UI, `UserToolProviderFactory` |
| Security & ops | ✅ Complete | Workflow scoping, approve lock, rate limit by identity, OTEL, stale/failed alerts |

---

## Architecture phases (build map)

Phases 1–13 from [`ARCHITECTURE.md`](./ARCHITECTURE.md) are **implemented**.

| Phase | Theme | Key deliverables | Verified |
|-------|-------|------------------|----------|
| **1** | Data layer | Alembic, psycopg pool, migration `0001`, 12+ ORM tables | ✅ CI + GCP |
| **2** | Summary embeddings | `EmbeddingIndex`, pgvector `0002`, meeting search | ✅ Tests + GCP |
| **3** | Async | ARQ worker, `submit` vs `run_batch_workflow`, `GET /workflows/{id}` | ✅ GCP + Postman |
| **4** | ASR | OpenAI adapter, upload store (local/S3/GCS), `POST /batch/upload` | ✅ Tests; GCS on GCP |
| **5** | Approvals | `approval_requests`, `ApprovalService`, `AgentRuntime.resume` | ✅ Tests + frontend inbox |
| **6** | Tools | `services/tools/` package, SendGrid/Google/Slack providers | ✅ Live on GCP |
| **7** | Retrieval | Chunk/decision embeddings `0004`, RAG `QueryAnswerer`, cursor pagination | ✅ Tests + frontend |
| **8** | Hardening | Auth, structlog, `/ready`, slowapi, ruff/mypy/CI | ✅ |
| **9–12** | Tools + frontend + security | Live integrations, Vite UI, workflow scoping, ops monitors | ✅ |
| **14** | Pub/Sub worker | Pub/Sub publish, push handler, scale-to-zero worker deploy | ✅ |

---

## Tool wiring (deploy fallback + per-user)

| Channel | Deploy fallback | Per-user (when connected) |
|---------|-----------------|---------------------------|
| Slack | One webhook/bot for deploy | User workspace OAuth; **Meeting Assistant bot** in chosen channels |
| Email | SendGrid from one sender | Branded **Meeting Assistant** From; per-user notification addresses |
| Calendar | Service account calendar | **Assistant calendar** organizer; user invited as attendee |
| Resolution | `build_tool_providers(settings)` | `UserToolProviderFactory.for_user(meeting.user_id)` |

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) ADR-15 (authorize user, act as app) and ADR-16 (per-user factory).

---

## Test & CI coverage

- **170 tests** across 31 modules (`uv run pytest`).
- **CI:** ruff, mypy, full SQLite suite; Postgres smoke (migrations + embeddings).
- **Gaps:** No live integration tests against SendGrid/Google/Slack; no full Postgres E2E; no frontend tests; `GET /meetings/{id}/tasks` lacks user scoping.

Canonical local flow: `tests/test_api.py::test_batch_ingestion_and_retrieval`.

---

## Known gaps (see ARCHITECTURE.md)

- `GET /meetings/{id}/tasks` — no `assert_user_scope` (IDOR for multi-tenant).
- Transcript queue ack/nack unused; background tool backoff blocks executor thread.
- Jira live integration deferred.
- Real-time ASR — v2.

---

## Phase 14 — Pub/Sub triggered worker (handoff)

**Goal:** Stop paying for an always-on Cloud Run worker. Today the worker runs ARQ against Redis with **minimum instances = 1** so jobs are picked up immediately. Replace the Redis/ARQ **job dispatch** path with **Cloud Pub/Sub push → Cloud Run worker HTTP handler**, so the worker scales to **zero** and wakes only when a batch job is published.

**Current flow (GCP):**

```
POST /batch (202) → ArqBatchJobQueue → Redis → always-on ARQ worker → run_batch_workflow
```

**Target flow (GCP):**

```
POST /batch (202) → PubSubBatchJobQueue → Pub/Sub topic
                                              ↓ push (per message)
                         Cloud Run worker (min-instances=0) POST /internal/jobs/batch
                                              → run_batch_workflow → 200 ack
```

**Keep unchanged:** `BatchJobQueue` protocol (ADR-2), `submit_batch_meeting` / `run_batch_workflow` split (ADR-6), `workflow_runs` as job record (ADR-7). Local dev and Docker Compose can keep `JOB_QUEUE_PROVIDER=arq` + Redis.

### Feature ids (implement in order — one at a time per AGENTS.md)

| Order | Feature id | Deliverable |
|-------|------------|-------------|
| 1 | `deploy-pubsub-gcp` | Topic, push subscription, IAM, Makefile deploy vars; worker `min-instances=0` |
| 2 | `job-queue-pubsub` | `PubSubBatchJobQueue` + `JOB_QUEUE_PROVIDER=pubsub` in bootstrap |
| 3 | `worker-pubsub-push` | HTTP push handler on worker; replace `arq` entrypoint when pubsub mode |
| 4 | `ops-pubsub-readiness` | Readiness checks without ARQ heartbeat; tests |

### Implementation checklist

#### 1. `deploy-pubsub-gcp`

- [x] Add env vars to `deploy/.env.prod.example`: `PUBSUB_TOPIC`, `PUBSUB_PROJECT`, `JOB_QUEUE_PROVIDER=pubsub` (GCP prod).
- [x] Makefile targets: create/update Pub/Sub topic + **push subscription** (endpoint = worker Cloud Run URL + push path).
- [x] IAM: API Cloud Run SA → `roles/pubsub.publisher`; Pub/Sub push SA → `roles/run.invoker` on worker service.
- [x] `deploy-worker`: set `--min-instances=0` when `JOB_QUEUE_PROVIDER=pubsub` (ARQ keeps `min-instances=1`).
- [x] Document rollback: flip `JOB_QUEUE_PROVIDER` back to `arq` and restore min-instances if needed.
- [ ] Optional: remove or downsize Upstash Redis if only used for ARQ job queue (keep if transcript queue still uses Redis).

#### 2. `job-queue-pubsub`

- [x] New class `PubSubBatchJobQueue` in `src/meeting_assistant/services/jobs.py`.
- [x] Publish JSON message: `{ "workflow_run_id": int, "payload": dict }` + W3C trace context in attributes (match `inject_trace_context`).
- [x] Extend `build_batch_job_queue()` for `job_queue_provider == "pubsub"`.
- [x] Config in `core/config.py`: `pubsub_topic`, `pubsub_project`, optional `pubsub_emulator_host` for local tests.
- [x] Add `google-cloud-pubsub` dependency.
- [x] Unit tests with mocked publisher (`tests/test_pubsub_queue.py`).

#### 3. `worker-pubsub-push`

- [x] New push route on worker FastAPI app (`worker_app.py`) instead of ARQ when pubsub mode.
- [x] Decode Pub/Sub push envelope (base64 `message.data`); validate **Pub/Sub OIDC token** on `Authorization` header.
- [x] Call `bootstrap_container()` → `orchestrator.run_batch_workflow(workflow_run_id, payload)`.
- [x] Return 200 on success (ack); 500 on transient failure (Pub/Sub retry).
- [x] Idempotency: rely on existing `workflow_runs.status == PENDING` guard in orchestrator (ADR-7).
- [x] Update `scripts/cloudrun_worker_entrypoint.sh` to run uvicorn worker app when `JOB_QUEUE_PROVIDER=pubsub`.

#### 4. `ops-pubsub-readiness`

- [x] When `job_queue_provider=pubsub`, API `/ready` skips ARQ heartbeat (`check_worker_health` → skipped with detail).
- [x] Worker `/ready`: DB check only (no Redis ARQ key); Makefile sets `READINESS_CHECK_REDIS=false` on worker.
- [x] Tests in `test_worker_readiness.py` / `test_readiness.py` for pubsub branch.
- [x] Update ARCHITECTURE.md adapter matrix and Phase 14 note.

### Acceptance criteria (GCP live)

1. Set worker `min-instances=0`; no running worker instances when idle.
2. `POST /api/v1/meetings/batch` (async) returns 202; within ~1–2 min workflow moves `PENDING` → `done` (or `awaiting_approval`).
3. Cloud Run worker instance count scales up on publish, scales down after job completes.
4. `GET /api/v1/workflows/{id}` shows tool executions and agent steps as today.
5. Quality gate: `uv run ruff check src tests && uv run mypy src/meeting_assistant && uv run pytest`.
6. Mark each feature `pass` in `features.json` with evidence + `testedAt`.

### Key files to touch (next chat)

| File | Change |
|------|--------|
| `src/meeting_assistant/services/jobs.py` | `PubSubBatchJobQueue`, factory branch |
| `src/meeting_assistant/bootstrap.py` | Wire pubsub queue |
| `src/meeting_assistant/core/config.py` | Pub/Sub settings |
| `src/meeting_assistant/worker.py` or new `worker_push.py` | Push HTTP handler |
| `scripts/cloudrun_worker_entrypoint.sh` | Pub/Sub vs ARQ mode |
| `Makefile` | Pub/Sub infra + `deploy-worker` min-instances |
| `deploy/.env.prod.example` | Pub/Sub env vars |
| `tests/test_jobs.py` / new `tests/test_pubsub_queue.py` | Publisher + handler tests |
| `ARCHITECTURE.md` | ADR / adapter matrix (after implementation) |

---

## Development workflow

### Local (zero-infra)

```bash
uv sync --extra dev
uv run uvicorn meeting_assistant.main:app --reload
uv run pytest
```

Defaults: SQLite, heuristic planner/embeddings, stub tools, sync batch.

### Production-shaped local

```bash
cp .env.production.example .env.production
export MEETING_ASSISTANT_ENV_FILE=.env.production
uv run uvicorn meeting_assistant.main:app --reload
uv run arq meeting_assistant.worker.WorkerSettings
```

Or Docker Compose:

```bash
cp .env.compose.example .env.compose
make compose-up
make compose-smoke
```

### GCP deploy

```bash
# Fill deploy/.env.prod from deploy/.env.prod.example
make deploy-bootstrap   # or deploy-api + deploy-worker
```

### Updating progress

When you complete a feature:

1. Run verification (tests + manual check if needed).
2. Edit `features.json`: `"status": "pass"`, `evidence`, `testedAt`.
3. Update this file if the milestone is significant.

---

## Key references

| Doc / file | Purpose |
|------------|---------|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | System design, ADRs, API surface, production checklist |
| [`AGENTS.md`](./AGENTS.md) | Agent/dev environment quick start |
| [`features.json`](./features.json) | Feature checklist (pass / not_started) |
| `.env.production.example` | App-level production env |
| `deploy/.env.prod.example` | GCP infra env |
| `Makefile` | Cloud Run deploy targets |

---

## Suggested next work

1. **Tasks endpoint scoping** — add `assert_user_scope` to `GET /meetings/{id}/tasks`.
2. **Jira live** — re-enable deploy config and planner blocks when needed.
3. **Real-time ASR** — v2 product surface; batch-first v1 is complete.
