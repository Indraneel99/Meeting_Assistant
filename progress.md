# Meeting Assistant — Progress & Roadmap

Last updated: 2026-07-26

## Executive summary

Meeting Assistant is a **modular monolith** FastAPI backend with a complete batch ingestion → agent → retrieval loop. The core product is **deployed on GCP (Cloud Run)** and verified end-to-end via Postman: batch ingestion runs, the agent plans and executes tools, workflow status updates correctly, and Postgres is populated as expected.

What remains for a full production product:

2. **User login (JWT)** — replace browser API-key panel with proper sessions.
3. **Security & ops** — worker health, alerting (approve lock ✅, rate limit by identity ✅).
3. **Optional:** Jira live integration (deferred), real-time ASR (v2).

Use [`features.json`](./features.json) as the machine-readable source of truth for feature status. Update it when a feature is verified (set `status: "pass"`, add `evidence` and `testedAt`).

---

## Current state (verified)

| Area | Status | Notes |
|------|--------|-------|
| GCP API (Cloud Run) | ✅ Deployed | Batch, search, query, workflows reachable from Postman |
| GCP Worker (ARQ) | ✅ Deployed | Async batch pipeline off HTTP thread |
| Cloud SQL Postgres | ✅ Running | pgvector migrations applied on startup |
| Redis / ARQ | ✅ Configured | Upstash `rediss://` for job queue |
| OpenAI (LLM, embed, ASR, query) | ✅ Configured | Production-shaped env in `.env.production.example` |
| GCS audio storage | ✅ Configured | Upload + ASR source reads |
| Agent loop | ✅ Verified | Plan → tool execute → complete meeting; DB updated |
| Tool integrations | ✅ v1 deploy-level | Live Slack/SendGrid/Calendar on GCP; Phase 13 → per-user connect + app identity |
| Auth | ✅ Enabled | Scoped `X-API-Key` + JWT login (`auth-user-login`); frontend Sign in panel |
| Frontend | ✅ MVP + Integrations | Upload, workflow, search, query, approvals, Settings → Integrations |
| User integrations | ✅ Phase 13 complete | Schema + OAuth API + Settings UI + per-provider connect + per-user tool factory |

---

## Architecture phases (build map)

Phases 1–8 from [`ARCHITECTURE.md`](./ARCHITECTURE.md) are **implemented**. The table below maps each phase to deliverables and verification.

| Phase | Theme | Key deliverables | Verified |
|-------|-------|------------------|----------|
| **1** | Data layer | Alembic, psycopg pool, migration `0001`, 12 ORM tables | ✅ CI + GCP |
| **2** | Summary embeddings | `EmbeddingIndex`, pgvector `0002`, meeting search | ✅ Tests + GCP |
| **3** | Async | ARQ worker, `submit` vs `run_batch_workflow`, `GET /workflows/{id}` | ✅ GCP + Postman |
| **4** | ASR | OpenAI adapter, upload store (local/S3/GCS), `POST /batch/upload` | ✅ Tests; GCS on GCP |
| **5** | Approvals | `approval_requests`, `ApprovalService`, `AgentRuntime.resume`, admin HTML | ✅ Tests; stub calendar |
| **6** | Tools | `services/tools/` package, SendGrid/Google/Slack/Jira providers | ✅ Live on GCP (v1 deploy-level) |
| **7** | Retrieval | Chunk/decision embeddings `0004`, RAG `QueryAnswerer`, cursor pagination | ✅ Tests + Postman |
| **8** | Hardening | Auth, structlog, `/ready`, slowapi, ruff/mypy/CI | ✅ |
| **9–12** | Tools + frontend + security | Live integrations, Vite UI, workflow scoping | ✅ |
| **13** | User integrations | `user_integrations`, OAuth API, Settings UI, per-user tool factory, app-branded outbound | ✅ |

---

## Adapter matrix (v1 deploy-level → Phase 13 per-user)

| Concern | v1 (GCP today) | Phase 13 target |
|---------|----------------|-----------------|
| Slack | One webhook/bot for deploy | User connects workspace; **Meeting Assistant bot** posts to chosen channels |
| Email | SendGrid from one sender | Branded **Meeting Assistant** From; per-user notification addresses |
| Calendar | Service account calendar | **Assistant calendar** organizer; user invited as attendee |
| Tools wiring | `build_tool_providers(settings)` env singleton | `UserToolProviderFactory(meeting.user_id)` |

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) ADR-15 (authorize user, act as app) and ADR-16 (per-user factory).

---

## Test & CI coverage

- **169 tests** across 31 modules (`uv run pytest`).
- **CI:** ruff, mypy, full SQLite suite; Postgres smoke (migrations + embeddings).
- **Gaps:** No live integration tests against SendGrid/Google/Slack/Jira; no full Postgres E2E; no frontend tests.

Canonical local flow: `tests/test_api.py::test_batch_ingestion_and_retrieval`.

---

## Roadmap to end-to-end product

### Phase 13 — User integrations (complete)

**Goal:** Each user connects the channels they want; agent actions appear as **Meeting Assistant**, not as the user.

**Principle (ADR-15):** User **authorizes** → app **acts** with its own identity (like Cursor pushing as `cursor[bot]`).

| Integration | User connects | Outbound identity | Feature id |
|-------------|---------------|-------------------|------------|
| Slack | Workspace OAuth install | Meeting Assistant **bot** | `integrations-slack-workspace` |
| Email | Notification email prefs | `Meeting Assistant <notifications@domain>` | `integrations-email-preferences` |
| Calendar | Optional Google read; assistant writes | Invite from **assistant calendar** | `integrations-calendar-assistant` |

**Build order:**

1. `integrations-schema` — `user_integrations` migration + encryption ✅
2. `integrations-oauth-api` — connect / callback / disconnect / settings ✅
3. `integrations-settings-ui` — frontend Integrations page ✅
4. `integrations-slack-workspace` ✅
5. `integrations-email-preferences` ✅
6. `integrations-calendar-assistant` ✅
7. `integrations-per-user-tools` — planner `available_tools` + `integration_not_connected` ✅
8. `auth-user-login` — JWT sessions (replace API key in browser) ✅

---

### Phase 9 — Real tool integrations (v1 complete)

**Goal:** Agent actions reach real external systems in production.

| Tool | Config | Credentials needed | Approval | Status |
|------|--------|-------------------|----------|--------|
| Slack | `SLACK_PROVIDER=webhook` or `api` | Webhook URL or Bot token + channel | No | ✅ Live on GCP |
| Email | `EMAIL_PROVIDER=sendgrid` | SendGrid API key, verified sender | No | ✅ Live on GCP |
| Calendar | `CALENDAR_PROVIDER=google` | Service account or OAuth; `uv sync --extra tools` | Yes (two-phase) | ✅ Live on GCP |
| Jira | `JIRA_PROVIDER=rest` | Jira Cloud URL, email, API token, project key | No | Commented out / deferred |
| Auth | `AUTH_ENABLED=true` | API keys in Secret Manager (`user:key` format) | No | ✅ Live on GCP |

**Tasks:**

1. Create Slack app / webhook; add secrets to GCP Secret Manager.
2. SendGrid: verify sender domain; set `MEETING_ASSISTANT_EMAIL_SENDGRID_*` env vars.
3. Google Calendar: service account with calendar scope; share target calendar.
4. Jira: API token; test `jira.create_issue` idempotency labels.
5. Run batch meetings with transcript text that triggers each tool keyword.
6. Update `features.json` per tool when live-verified.

**Acceptance:** Postman batch → workflow `done` or `awaiting_approval` → real Slack message / email / calendar hold / Jira ticket visible in target system.

---

### Phase 10 — Frontend

**Goal:** Product UI for ingest, status, search, query, and approvals (replace Postman + minimal admin HTML).

**Status:** MVP scaffold complete in `frontend/` (Vite + React + TypeScript). Run API on `:8000`, then `cd frontend && npm install && npm run dev` for `:5173`. CORS enabled via `MEETING_ASSISTANT_CORS_ORIGINS`. Search/Query screens include chunk search, cursor pagination, and RAG citations with retrieved context.

**Recommended stack (fits current API):**

- **Framework:** Next.js or Vite + React (TypeScript).
- **Auth:** `X-API-Key` header (match `MEETING_ASSISTANT_AUTH_API_KEYS`) or JWT if you add a login service later.
- **API client:** OpenAPI-generated client from `/openapi.json`.

**MVP screens:**

| Screen | API endpoints |
|--------|---------------|
| Upload / paste transcript | `POST /batch`, `POST /batch/upload` |
| Workflow status | `GET /workflows/{id}` |
| Approval inbox | `GET /workflows/{id}/approvals`, `POST /approvals/{id}/approve\|reject` |
| Meeting search | `GET /meetings/search` |
| Ask a question (RAG) | `POST /query` |
| Meeting detail | `GET /meetings/{id}/tasks`, decisions via search |

**Tasks:**

1. Scaffold app in `frontend/` (or separate repo).
2. Add CORS to FastAPI if browser calls API directly.
3. Implement auth header injection and error handling.
4. Deploy frontend (Vercel, Cloud Run static, or Firebase Hosting).
5. Enable `AUTH_ENABLED=true` on API.

---

### Phase 11 — Security hardening

**Goal:** Safe for external / multi-tenant use.

| Item | Risk today | Fix |
|------|------------|-----|
| Workflow/approval IDOR | Scoped keys/JWT must match workflow owner; unscoped keys are admin bypass | ✅ `assert_resource_user_scope` on workflow + approval routes |
| Rate limits by IP | Shared NAT bypass | ✅ Key limits by API key / JWT user |
| Concurrent approve | Double-approve race | ✅ Redis SET NX lock when auth + Redis |
| Admin HTML | No user scoping | Fold into frontend or add scope checks |

Enable auth in prod: set `AUTH_ENABLED=true` in `deploy/.env.prod`, configure `GCP_AUTH_KEYS_SECRET`.

---

### Phase 12 — Ops & observability

| Item | Status | Action |
|------|--------|--------|
| Structlog JSON | ✅ | Ship to Cloud Logging |
| OTEL tracing | ✅ | API + worker OTLP export; ARQ trace propagation; tool/batch spans |
| Worker readiness | ✅ | `/ready` checks ARQ Redis heartbeat; worker Cloud Run `/ready` |
| Stale workflows | ✅ | GET /admin/ops/stale-workflows + `stale_workflow_detected` logs |
| DLQ / failed tools | ✅ | GET /admin/ops/failed-tools + `failed_tool_detected` logs |

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

Copy `.env.production.example` → `.env.production`, point at local Postgres + Redis, run API + worker:

```bash
export MEETING_ASSISTANT_ENV_FILE=.env.production
uv run uvicorn meeting_assistant.main:app --reload
uv run arq meeting_assistant.worker.WorkerSettings
```

Or use Docker Compose (Postgres + Redis + API + ARQ worker):

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

1. Run the verification (test or manual Postman/GCP check).
2. Edit `features.json`: set `"status": "pass"`, fill `evidence` and `testedAt`.
3. Update the summary table in this file if the milestone is significant.

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

## Suggested priority order

1. **Phase 13 user integrations** — schema → OAuth API → Settings UI → per-user tool factory.
2. **User login (JWT)** — before exposing OAuth in browser (`auth-user-login`).
3. **Security hardening** — worker health, alerting (approve lock ✅, rate limit by identity ✅).
4. **Ops** — OTEL tracing ✅, failed tool alerts ✅ (stale workflow alerting ✅).
5. **Jira live** — deferred.
6. **Real-time ASR** — v2.
