# Meeting Assistant — Architecture Reference

Modular monolith: single FastAPI service, protocol-based adapters, `bootstrap.py` as the single wiring boundary. Default dev stack is SQLite + stubs + sync; production enables Postgres, Redis/ARQ, OpenAI, and auth via config only.

---

## System topology

```
                         ┌─────────────────────────────────────┐
                         │     Frontend (Vite+React) + Admin    │
                         └──────────────────┬──────────────────┘
                                            │ HTTP
                         ┌──────────────────▼──────────────────┐
                         │  FastAPI (Phase 8: auth, logs, limits) │
                         │  /health /ready  (public)            │
                         │  /api/v1/*       (protected opt-in)  │
                         │  /api/v1/integrations/*  /auth/*     │
                         └──────────┬─────────────┬────────────┘
                                    │             │
              ┌─────────────────────┘             └────────────────────┐
              ▼ sync / 202 async                                        ▼
     ┌─────────────────┐                                         ┌──────────────┐
     │ BatchOrchestrator│◄────────────────────────────────────│ ARQ Worker   │
     │ submit / run     │         run_batch_workflow            │ (Phase 3)    │
     └────────┬─────────┘                                         └──────┬───────┘
              │                                                          │
    ┌─────────┼─────────┬──────────┬──────────┬──────────┐            │
    ▼         ▼         ▼          ▼          ▼          ▼            │
  ASR    Normalizer  Embedder  AgentRuntime  ToolExecutor  Queue       │
    │         │         │          │            │          │            │
    │         │         │          │     UserToolProviderFactory       │
    │         │         │          │     (per-user integrations)       │
    └─────────┴─────────┴──────────┴────────────┴──────────┘            │
                              │                                         │
              ┌───────────────┼───────────────┐                         │
              ▼               ▼               ▼                         │
         PostgreSQL      Redis (opt)    Object storage (opt) ◄──────────┘
         SQLite (dev)    ARQ jobs
         user_integrations
```

**Read path (isolated module):** `QueryService` → `EmbeddingIndex` → `QueryAnswerer` (RAG). No agent loop on search/query.

---

## Core product loop

```
POST /batch (or /batch/upload)
  → [async: enqueue] run_batch_workflow
  → ASR → normalize → chunk + embed chunks
  → context load (semantic past meetings)
  → AgentRuntime: plan → validate → ToolExecutor
  → complete_meeting (summary + summary_embedding + decisions w/ topic_embedding)
  → workflow: done | awaiting_approval | failed

awaiting_approval:
  → ApprovalService: approve/reject → finalize_approval → AgentRuntime.resume → done

Read:
  → GET search / chunks/search / decisions (semantic + pagination)
  → POST /query (multi-source retrieve → QueryAnswerer → citations)
```

---

## Phased build map


| Phase | Theme              | Key artifacts                                                                                           |
| ----- | ------------------ | ------------------------------------------------------------------------------------------------------- |
| **1** | Data layer         | Alembic, psycopg pool, `initialize_database()`, migration `0001`                                        |
| **2** | Summary embeddings | `EmbeddingIndex`, `EmbeddingVector`, pgvector `0002`, search uses stored vectors                        |
| **3** | Async              | `TranscriptQueue`, `BatchJobQueue`, `submit` vs `run_batch_workflow`, ARQ worker, `GET /workflows/{id}` |
| **4** | ASR                | `ASRAdapter` / resolvers / `Transcriber`, upload store, `POST /batch/upload`, `ASRError` taxonomy       |
| **5** | Approvals          | `approval_requests`, `ApprovalService`, `AgentRuntime.resume`, admin UI                                 |
| **6** | Tools              | `services/tools/` package, `build_tool_providers`, SendGrid/Google/Slack/Jira                           |
| **7** | Retrieval          | Chunk/decision embeddings `0004`, chunk search, RAG `QueryAnswerer`, cursor pagination                  |
| **8** | Hardening          | Auth, structlog, OTEL, `/ready`, slowapi, ruff/mypy/CI                                                  |
| **9–12** | Prod tools + frontend + security | Live Slack/SendGrid/Calendar, Vite frontend, workflow scoping | ✅ v1 deploy-level tools |
| **13** | User integrations  | `user_integrations`, OAuth connect, Settings UI, `UserToolProviderFactory`, app-branded outbound identity | ✅ complete |
| **14** | Pub/Sub worker     | `PubSubBatchJobQueue`, push handler, scale-to-zero worker on GCP | ✅ complete |
| **15** | User login UI      | Email/password + Google Sign-In; remove browser API-key UX | ✅ complete |


---

## Architectural decisions (ADRs)

### ADR-1: Modular monolith, not microservices (v1)

**Decision:** One deployable Python service; extract later at existing seams.  
**Rationale:** Validated agent loop locally; production work is adapter swap + config, not rewrite.  
**Impact:** `bootstrap_container()` is the extraction boundary for worker, future read service, Kafka producer.

### ADR-2: Protocol + factory for every external system

**Decision:** `Planner`, `Embedder`, `EmbeddingIndex`, `TranscriptQueue`, `BatchJobQueue`, `ASRAdapter`, `AudioSourceResolver`, `Transcriber`, `ToolProvider`, `QueryAnswerer` — each has `build_*()` in bootstrap.  
**Rationale:** Copy one pattern; dev defaults (heuristic, in-memory, stub) without code forks.  
**Impact:** New provider = new class + factory branch, not orchestrator changes.

### ADR-3: Schema via Alembic, not `create_all()` at runtime

**Decision:** Migrations are versioned; startup runs `upgrade head`; legacy SQLite gets stamp + compat shim.  
**Rationale:** Multi-instance Postgres, CI smoke, pgvector DDL.  
**Impact:** Models and migrations are dual contract — `alembic check` / discipline required.

### ADR-4: Embed once at write, search stored vectors at read

**Decision:** `summary_embedding`, `chunk_embedding`, `topic_embedding` set at ingest/complete; search never re-embeds corpus text.  
**Rationale:** Cost, stability, enables pgvector ANN indexes.  
**Impact:** Embedder config must match at write and read; dimension padding on Postgres path.

### ADR-5: Dialect-aware storage (`EmbeddingVector`)

**Decision:** SQLite = JSON text; Postgres = `vector(1536)` via type decorator + dialect-gated migrations.  
**Rationale:** Zero-infra local dev + prod ANN on same ORM types.  
**Impact:** Dev/prod ranking can differ (exact scan vs HNSW).

### ADR-6: Submit vs execute split (async)

**Decision:** `submit_batch_meeting()` creates durable rows + enqueues; `run_batch_workflow()` runs pipeline. `job_id == workflow_run_id`.  
**Rationale:** Long ASR/LLM off HTTP thread; poll `workflow_runs.status`.  
**Impact:** Two queue concepts: **BatchJobQueue** (async boundary) vs **TranscriptQueue** (in-pipeline staging, mostly publish+drain today).

### ADR-7: Workflow-as-job (no separate jobs table)

**Decision:** `workflow_runs` is the async job record; status machine is product truth.  
**Rationale:** Audit model already centered on `WorkflowRun`.  
**Impact:** Stale `PENDING` workflows need ops alerting; ARQ retries rely on `PENDING` idempotency guard.

### ADR-8: Human approval as first-class entity

**Decision:** Three layers: `workflow_runs.status`, `tool_executions.status`, `approval_requests` row. Calendar: two-phase `execute` / `execute_after_approval`.  
**Rationale:** Pause without losing planner state; resume from `agent_steps` + `tool_executions`.  
**Impact:** `ApprovalService` owns continuation, not `BatchOrchestrator` re-ingest.

### ADR-9: Agent resume from persistence (event-sourced-ish)

**Decision:** `AgentRuntime.resume()` rebuilds planner history from `agent_steps`, continues at `iteration_count + 1`, `seen_signatures` from DB.  
**Rationale:** Survives process boundaries (API approve vs worker that paused).  
**Impact:** Last planner step JSON must be sufficient state; multi-pause workflows are v1-limited.

### ADR-10: Tool executor owns idempotency; providers get outbound keys

**Decision:** SHA-256 per workflow run + tool + payload in DB; same key passed to SendGrid/Jira/Google/Slack metadata.  
**Rationale:** Internal authority + vendor reconciliation (`provider_message_id`).  
**Impact:** Jira labels / iCalUID are best-effort external dedup, not transactional.

### ADR-11: Read module isolation (`QueryService`)

**Decision:** Retrieval routes → `QueryService` → `EmbeddingIndex` + `QueryAnswerer`; no agent on read path.  
**Rationale:** v2 extract to read-only service / replica without moving write path.  
**Impact:** `/query` does 3 retrievals (3 query embeds) — batch embed cache is future optimization.

### ADR-12: Auth opt-in with router-level + resource-level scope

**Decision:** `auth_enabled=false` default; `require_auth` on `/api/v1/*` and `/admin/*`; `assert_user_scope` on batch, retrieval, workflows, and approvals.  
**Rationale:** Local hello-world unchanged; prod flips env.  
**Impact:** Scoped API keys/JWT subject must match workflow owner; unscoped keys remain admin-style bypass for ops.

### ADR-13: Liveness vs readiness

**Decision:** `/health` always OK; `/ready` checks DB (+ Redis when used, optional embedder probe) → 503.  
**Rationale:** K8s/load balancer patterns.  
**Impact:** When `READINESS_CHECK_WORKER=true` with async + ARQ, `/ready` checks ARQ worker heartbeat in Redis. With async + Pub/Sub (`JOB_QUEUE_PROVIDER=pubsub`), the worker check is skipped — Pub/Sub push invokes the scale-to-zero worker on demand. The worker Cloud Run service exposes its own `/ready` endpoint (database + optional embedder; no ARQ heartbeat).

### ADR-14: CI: fast SQLite suite + Postgres smoke

**Decision:** ruff, mypy, full pytest on SQLite; Postgres job runs migrations + embedding tests.  
**Rationale:** Phase 1 exit criteria without slowing every PR with full Postgres matrix.  
**Impact:** Full E2E on Postgres is partial coverage.

### ADR-15: User integrations — authorize user, act as Meeting Assistant

**Decision:** Outbound tool actions use **app identity**, not user impersonation. Users connect integrations to grant permission and set preferences; messages/emails/events appear as **Meeting Assistant** (Slack bot, branded email sender, assistant-owned calendar organizer).  
**Rationale:** Matches GitHub-App / Cursor-bot pattern: user authorizes, app acts with its own visible identity. Avoids “send as my Gmail” and Slack user-token impersonation.  
**Impact:**

| Channel | User connects | Action identity | Per-user storage |
| ------- | ------------- | --------------- | ---------------- |
| Slack | Workspace app install (OAuth) | Bot **Meeting Assistant** | `workspace_id`, allowed `channel_ids` |
| Email | Notification preferences | `Meeting Assistant <notifications@domain>` via SendGrid | recipient emails, opt-in flags |
| Calendar | Optional Google read (availability) | Events on **assistant calendar**, user invited as attendee | invite email, read OAuth token (encrypted) |
| Jira | Atlassian OAuth (future) | Issues filed as app/bot account | site URL, project prefs |

Deploy-level secrets (SendGrid API key, Slack app client_id/secret, assistant calendar service account) remain **global**. Per-user rows hold authorization + preferences only — not “send as user” credentials for Slack/email.

### ADR-16: Per-user tool provider factory (Phase 13)

**Decision:** `UserToolProviderFactory` resolves `ToolProvider` at execution time from `meeting.user_id`, alongside deploy-level `build_tool_providers(settings)` fallback. Planner receives `available_tools` based on connected integrations.  
**Rationale:** v1 env-only tools work for single-tenant GCP; multi-user product requires per-user channel/recipient/calendar prefs.  
**Impact:** `ToolExecutor.execute()` loads meeting owner → factory → provider instance or `integration_not_connected`. Existing `ToolProvider` protocol unchanged. v1 deploy-level providers remain as optional org fallback when user has not connected.

### ADR-17: Login auth vs integrations OAuth (Phase 15)

**Decision:** User **login** (who you are) is separate from **integrations OAuth** (what the app may do on your behalf). Login supports email+password and Google Sign-In (`openid`, `email`, `profile`). Integrations OAuth (Phase 13) keeps existing scopes — e.g. Google Calendar **read** for availability — stored in `user_integrations`, not mixed with login sessions.

**Rationale:** Browser users should not paste API keys from Secret Manager. Google login proves identity; integrations Google connect grants calendar/Slack permissions later in Settings. Separate OAuth clients (or clearly separate redirect paths/scopes) avoid consent-screen confusion and token misuse.

**Impact:**

| Concern | Login (Phase 15) | Integrations (Phase 13) |
| ------- | ---------------- | ------------------------ |
| Purpose | Authenticate user → JWT | Authorize tool actions |
| Google scopes | `openid email profile` | Calendar read, etc. |
| Storage | `user_auth_identities` or users.password_hash | `user_integrations` encrypted tokens |
| Frontend | `/login`, Sign in with Google | Settings → Integrations |
| M2M / ops | `X-API-Key` in Secret Manager (Postman, scripts) | Unchanged |

JWT `sub` continues to map to `users.external_id` for `assert_user_scope` and batch ownership.

---

## Adapter matrix (config → implementation)

### Platform services (deploy-level)


| Concern          | Config knob             | Dev default             | Production                 |
| ---------------- | ----------------------- | ----------------------- | -------------------------- |
| Database         | `DATABASE_URL`          | SQLite                  | `postgresql+psycopg://`    |
| Embeddings       | `EMBEDDING_PROVIDER`    | heuristic               | openai                     |
| Index backend    | inferred from DB URL    | InMemory                | PgVector                   |
| Batch mode       | `BATCH_PROCESSING_MODE` | sync                    | async                      |
| Job queue        | `JOB_QUEUE_PROVIDER`    | inprocess               | arq (Compose) / pubsub (GCP) |
| Transcript queue | `QUEUE_PROVIDER`        | memory                  | redis                      |
| ASR              | `ASR_PROVIDER`          | openai (manual text ok) | openai + upload/S3         |
| Planner          | `LLM_PROVIDER`          | heuristic fallback      | openai                     |
| Query            | `QUERY_PROVIDER`        | heuristic               | openai                     |
| Auth             | `AUTH_ENABLED`          | false                   | JWT (email/Google login); API key for ops/M2M |

### Tool outbound identity (deploy fallback + per-user)

| Tool | Deploy fallback (v1) | Per-user (Phase 13) | Deploy config | Per-user config |
| ---- | -------------------- | ------------------- | ------------- | --------------- |
| Slack | One webhook/bot for whole deploy | **Meeting Assistant** bot in user's workspace | `SLACK_PROVIDER`, webhook URL | OAuth install + channel picker |
| Email | SendGrid from one sender | **Meeting Assistant** branded sender + user recipient prefs | `EMAIL_PROVIDER`, SendGrid key | `email_prefs` integration row |
| Calendar | Service account calendar | **Meeting Assistant** calendar invites user as attendee | `CALENDAR_PROVIDER`, SA JSON | Google OAuth + assistant organizer |
| Jira | One API token (deferred) | App/bot Jira account (future) | `JIRA_PROVIDER` | Atlassian OAuth per user/org |

Deploy-level `*_PROVIDER` env vars in `services/tools/factory.py` remain as org fallback when a user has not connected. `UserToolProviderFactory` resolves per-user providers at execution time.


---

## Data model (12+ tables)


| Group       | Tables                                                                       | Notes                             |
| ----------- | ---------------------------------------------------------------------------- | --------------------------------- |
| Identity    | `users`, `user_auth_identities` *(Phase 15)*                               | `external_id` tenant key; login methods |
| Integrations | `user_integrations`                                                       | OAuth tokens (encrypted), prefs   |
| Content     | `meetings`, `meeting_chunks`, `transcript_artifacts`, `transcript_segments`  | Chunks carry `chunk_embedding`    |
| Agent audit | `workflow_runs`, `agent_steps`, `tool_executions`, `tool_execution_attempts` | Idempotency + retries             |
| Artifacts   | `tasks`, `decisions`                                                         | Decisions carry `topic_embedding` |
| Human gate  | `approval_requests`                                                          | 1:1 with gated `tool_execution`   |

### `user_integrations`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `id` | int PK | |
| `user_id` | FK → `users.id` | Owner |
| `provider` | enum | `slack`, `google`, `jira`, `email_prefs` |
| `status` | enum | `connected`, `revoked`, `expired`, `error` |
| `scopes` | text/json | Granted OAuth scopes |
| `access_token_enc` | text | Encrypted; never exposed to frontend |
| `refresh_token_enc` | text | Encrypted |
| `expires_at` | timestamptz | |
| `provider_account_id` | string | e.g. Slack `team_id`, Google `sub` |
| `settings_json` | json | e.g. `{ "channels": ["#product"], "notification_emails": ["alice@co.com"] }` |
| `connected_at`, `updated_at` | timestamptz | |

Unique constraint: `(user_id, provider, provider_account_id)`.

### `user_auth_identities` *(Phase 15)*

| Column | Type | Notes |
| ------ | ---- | ----- |
| `id` | int PK | |
| `user_id` | FK → `users.id` | Owner |
| `provider` | enum | `email_password`, `google` |
| `provider_subject` | string | Google `sub` or normalized email |
| `password_hash` | string | Nullable; only for `email_password` |
| `metadata_json` | json | e.g. `{ "name": "Alice" }` from Google profile |
| `created_at`, `updated_at` | timestamptz | |

Unique constraint: `(provider, provider_subject)`. Link Google login to existing email account when emails match (explicit merge rules in AuthService).

**Vectors:** `meetings.summary_embedding`, `meeting_chunks.chunk_embedding`, `decisions.topic_embedding` — all via `EmbeddingVector`.

---

## API surface


| Method | Path                                    | Phase | Notes                    |
| ------ | --------------------------------------- | ----- | ------------------------ |
| GET    | `/health`                               | 8     | Public liveness          |
| GET    | `/ready`                                | 8     | Public readiness         |
| POST   | `/api/v1/meetings/batch`                | 3     | 200 sync / 202 async     |
| POST   | `/api/v1/meetings/batch/upload`         | 4     | Multipart audio          |
| GET    | `/api/v1/workflows/{id}`                | 3     | Poll status              |
| GET    | `/api/v1/workflows/{id}/approvals`      | 5     | List pending             |
| POST   | `/api/v1/approvals/{id}/approve|reject` | 5     | Resume agent             |
| GET    | `/api/v1/meetings/search`               | 2,7   | Semantic + cursor        |
| GET    | `/api/v1/meetings/chunks/search`        | 7     | Chunk semantic           |
| GET    | `/api/v1/decisions`                     | 7     | Semantic (was substring) |
| GET    | `/api/v1/meetings/{id}/tasks`           | —     | Per meeting              |
| POST   | `/api/v1/query`                         | 7     | RAG + citations          |
| GET    | `/admin/approvals/{id}`                 | 5     | HTML approve UI (legacy; frontend inbox preferred) |
| POST   | `/api/v1/auth/login`                    | 13    | Legacy API-key → JWT (ops/Postman; superseded for browser by Phase 15) |
| POST   | `/api/v1/auth/register`                 | 15    | Email + password sign-up |
| POST   | `/api/v1/auth/login/email`              | 15    | Email + password sign-in → JWT |
| GET    | `/api/v1/auth/google/connect`           | 15    | Start Google login OAuth |
| GET    | `/api/v1/auth/google/callback`          | 15    | Google login callback → JWT + redirect |
| GET    | `/api/v1/auth/config`                   | 13    | Auth mode flags for frontend |
| GET    | `/api/v1/auth/me`                       | 13    | Current session (Bearer JWT or API key) |
| GET    | `/api/v1/integrations`                  | 13    | List connected integrations for current user |
| GET    | `/api/v1/integrations/{provider}/connect` | 13  | Start OAuth; returns redirect URL |
| GET    | `/api/v1/integrations/{provider}/callback` | 13 | OAuth callback (server-side token exchange) |
| DELETE | `/api/v1/integrations/{provider}`       | 13    | Disconnect / revoke |
| PATCH  | `/api/v1/integrations/{provider}/settings` | 13 | Update channels, notification emails, etc. |
| GET    | `/api/v1/integrations/{provider}/options` | 13  | e.g. list Slack channels after connect |
| GET    | `/admin/ops/stale-workflows`            | 12    | PENDING workflows beyond threshold |
| GET    | `/admin/ops/failed-tools`               | 12    | Failed tool executions / DLQ exhaustion |

---

## User integrations flow

```
User logs in (JWT/session or scoped API key)
  → Settings → Integrations UI
  → Connect Slack: OAuth workspace install → store bot token + team_id per user
  → Email prefs: set notification addresses (no Gmail send-as-user)
  → Connect Google (optional): read calendar for availability; writes use assistant calendar
  → PATCH settings: pick Slack channels, notification emails

Batch ingest (meeting.user_id)
  → Agent plans tools filtered by available_tools(user_id)
  → ToolExecutor → UserToolProviderFactory.for_user(user_id, tool_name)
  → Slack: post as Meeting Assistant bot to user's allowed channels
  → Email: SendGrid from notifications@yourdomain, Reply-To user if configured
  → Calendar: create on assistant calendar, invite user (approval gate unchanged)
```

**Authorization vs identity:** Connecting Slack grants the app permission to post in selected channels; messages always show the **Meeting Assistant** bot name and icon — not the user's Slack profile.

---

## User login flow (Phase 15)

```
User opens /login
  → Email + password: POST /auth/register or POST /auth/login/email → JWT
  → Google: GET /auth/google/connect → Google consent (profile only)
       → /auth/google/callback → link/create user → JWT → redirect frontend
  → Frontend stores Bearer token; API calls use Authorization header
  → JWT sub = users.external_id → batch/meetings/workflows scoped via assert_user_scope

Ops / Postman: X-API-Key from Secret Manager (no browser UI)
Integrations (post-login): Settings → connect Slack/Google calendar (Phase 13, separate OAuth)
```

---

## Known gaps and tradeoffs

**Resolved in Phase 13 / ops hardening:** per-user integrations (`UserToolProviderFactory`), workflow/approval user scoping, rate limits by API key/JWT identity, Redis approve lock, ARQ worker heartbeat in `/ready`, OTEL tracing on API + worker, stale workflow and failed tool alerting.

**Phase 14 (Pub/Sub worker):** GCP production can set `JOB_QUEUE_PROVIDER=pubsub` — API publishes batch jobs to Cloud Pub/Sub; worker scales to zero and wakes on push to `POST /internal/jobs/batch`. `/ready` skips ARQ heartbeat in pubsub mode; stale-workflow and failed-tool ops alerts unchanged.

**Remaining:**

- Transcript queue ack/nack unused in pipeline (publish+drain only).
- `background` tool backoff still blocks executor thread on `future.result()`.
- `GET /meetings/{id}/tasks` lacks user scoping (IDOR gap for multi-tenant — other retrieval routes are scoped).
- Jira live integration deferred (`tool-jira-live` in `features.json`).
- Real-time ASR streaming is a v2 candidate (`realtime-asr-streaming` in `features.json`).
- Browser login uses email/password + Google Sign-In (Phase 15). Legacy API-key exchange remains for ops/Postman only.

---

## v2 extraction candidates (seams already exist)

1. **Read service** — `QueryService`, `EmbeddingIndex`, retrieval routes, read replica.
2. **Ingest worker** — Pub/Sub push or ARQ + `run_batch_workflow` only (already separate process).
3. **Event bus** — replace `BatchJobQueue` Redis with Kafka producer; orchestrator unchanged.
4. **Real-time ASR** — different product surface; batch-first v1 stands.

---

## Key files


| File                                              | Role                               |
| ------------------------------------------------- | ---------------------------------- |
| `src/meeting_assistant/bootstrap.py`              | Single wiring point                |
| `src/meeting_assistant/services/orchestrator.py`  | submit / run_batch_workflow        |
| `src/meeting_assistant/services/agent.py`         | run / resume loop                  |
| `src/meeting_assistant/services/approvals.py`     | Human gate continuation            |
| `src/meeting_assistant/services/embeddings.py`    | Embed + search protocols           |
| `src/meeting_assistant/services/query.py`         | Read facade                        |
| `src/meeting_assistant/services/tools/factory.py` | Deploy-level tool providers (v1)     |
| `src/meeting_assistant/services/tools/user_factory.py` | Per-user provider factory |
| `src/meeting_assistant/services/integrations/service.py` | OAuth connect, token storage, settings |
| `src/meeting_assistant/api/routes/integrations.py` | Integrations HTTP API |
| `src/meeting_assistant/api/routes/auth_routes.py` | Login / session endpoints |
| `src/meeting_assistant/services/auth.py` | JWT issue, login/register logic *(Phase 15)* |
| `src/meeting_assistant/services/stale_workflows.py` | Stale workflow ops monitor |
| `src/meeting_assistant/services/failed_tools.py` | Failed tool ops monitor |
| `src/meeting_assistant/api/app.py`                | HTTP envelope (auth, logs, limits) |
| `migrations/versions/`                            | Schema contract (0001–0005; 0006 auth Phase 15) |


---

## Production checklist

```bash
# Data
export MEETING_ASSISTANT_DATABASE_URL="postgresql+psycopg://..."
uv run alembic upgrade head

# Async
export MEETING_ASSISTANT_BATCH_PROCESSING_MODE="async"
export MEETING_ASSISTANT_JOB_QUEUE_PROVIDER="arq"
export MEETING_ASSISTANT_QUEUE_PROVIDER="redis"
uv run arq meeting_assistant.worker.WorkerSettings

# Quality paths
export MEETING_ASSISTANT_EMBEDDING_PROVIDER="openai"
export MEETING_ASSISTANT_QUERY_PROVIDER="openai"
export MEETING_ASSISTANT_LLM_OPENAI_API_KEY="..."

# Ship gate
export MEETING_ASSISTANT_AUTH_ENABLED="true"
export MEETING_ASSISTANT_AUTH_API_KEYS="alice:secret"
export MEETING_ASSISTANT_LOG_JSON="true"
export MEETING_ASSISTANT_RATE_LIMIT_ENABLED="true"
export MEETING_ASSISTANT_READINESS_CHECK_WORKER="true"

# Per-user integrations (Phase 13)
export MEETING_ASSISTANT_INTEGRATIONS_ENCRYPTION_KEY="..."
export MEETING_ASSISTANT_INTEGRATIONS_OAUTH_REDIRECT_BASE="https://your-api.run.app"
export MEETING_ASSISTANT_SLACK_OAUTH_CLIENT_ID="..."
export MEETING_ASSISTANT_GOOGLE_OAUTH_CLIENT_ID="..."

# User login (Phase 15 — separate from integrations Google client)
export MEETING_ASSISTANT_AUTH_PASSWORD_LOGIN_ENABLED="true"
export MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_ENABLED="true"
export MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_CLIENT_ID="..."
export MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_CLIENT_SECRET="..."
export MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_REDIRECT_BASE="https://your-api.run.app"
```

Verify: `curl /ready` → `ready`; batch → approval → approve → `done`; `POST /query` returns citations.