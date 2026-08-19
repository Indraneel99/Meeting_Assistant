# Meeting Assistant — Progress & Roadmap

Last updated: 2026-08-19

## Executive summary

Meeting Assistant is a **modular monolith** FastAPI backend with a Vite+React frontend. Batch ingestion → agent → retrieval is deployed on GCP with Pub/Sub scale-to-zero workers, per-user integrations, and JWT auth.

**68 of 70 features pass** in [`features.json`](./features.json). Remaining work:

1. **Jira live integration** — deferred (`tool-jira-live`).
2. **Real-time ASR streaming** — v2 candidate (`realtime-asr-streaming`).

Use [`features.json`](./features.json) as the machine-readable source of truth.

---

## Current state (verified)

| Area | Status | Notes |
|------|--------|-------|
| GCP API (Cloud Run) | ✅ Deployed | Batch, search, query, workflows, integrations |
| GCP Worker (Pub/Sub push) | ✅ Deployed | Scale-to-zero; push → `POST /internal/jobs/batch` |
| Cloud SQL Postgres | ✅ Running | pgvector migrations applied on startup |
| Redis | ✅ Optional | Approval locks; job dispatch via Pub/Sub on GCP |
| Auth | ✅ Phase 15 | Email/password + Google Sign-In; API keys ops-only |
| Frontend | ✅ Complete | Upload, workflow, search, query, approvals, integrations, login |
| User integrations | ✅ Phase 13 | OAuth for Slack/Google calendar (separate from login OAuth) |

---

## Architecture phases (build map)

| Phase | Theme | Status |
|-------|-------|--------|
| **1–13** | Core product + integrations | ✅ |
| **14** | Pub/Sub worker | ✅ |
| **15** | User login (email/password + Google) | ✅ |

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) ADR-17 for login vs integrations OAuth separation.

---

## Phase 15 — User login UI ✅ Complete (2026-08-19)

**Goal:** Replace the sidebar **API key + email** sign-in with a proper **login page**: email/password registration and **Sign in with Google**. End users never see or paste API keys. Keep `X-API-Key` for Postman, scripts, and ops only.

### Implemented flow

```
/login → email + password → POST /auth/register or /auth/login/email → JWT
      → OR "Sign in with Google" → GET /auth/google/connect → callback → JWT (#fragment) → app
      → Protected routes require JWT when AUTH_ENABLED; Sign out clears session
Integrations (post-login): Settings → Slack/Google calendar (unchanged Phase 13 OAuth)
Ops: X-API-Key in Secret Manager (unchanged, not in UI)
```

### Features (all pass)

| Feature id | Deliverable |
|------------|-------------|
| `auth-identity-schema` | Migration `0006_user_auth_identities`, ORM, repository |
| `auth-email-password` | Register + email login, bcrypt, JWT |
| `auth-google-login` | Google login OAuth connect/callback, link-or-create user |
| `deploy-auth-gcp` | `deploy/.env.prod.example`, Makefile wiring |
| `frontend-auth-pages` | `/login`, `/register`, route guards, no API key UI |
| `security-auth-login-limits` | Rate limits on register/login/callback |

### GCP deploy checklist (manual)

1. Create Google OAuth client **Meeting Assistant Login** (Web application).
2. Redirect URI: `https://<api>/api/v1/auth/google/callback`
3. JS origin: frontend URL
4. Secret Manager: `AUTH_GOOGLE_LOGIN_CLIENT_SECRET`
5. Set `AUTH_LOGIN_ALLOW_DEV=false`, `CORS_ORIGINS=<frontend>` in `deploy/.env.prod`
6. `make deploy-api`

---

## Phase 14 — Pub/Sub worker

**Status:** ✅ Complete (2026-08-19). See `job-queue-pubsub`, `worker-pubsub-push`, `deploy-pubsub-gcp`, `ops-pubsub-readiness` in `features.json`.

---

## Known gaps

- `GET /meetings/{id}/tasks` — no user scoping (IDOR).
- Jira live deferred; real-time ASR v2.

---

## Development workflow

```bash
uv sync --extra dev
uv run uvicorn meeting_assistant.main:app --reload
uv run pytest
cd frontend && npm run dev
```

GCP: `make deploy-api deploy-worker` after filling `deploy/.env.prod`.

---

## Key references

| Doc | Purpose |
|-----|---------|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | ADRs, API surface, ADR-17 login vs integrations |
| [`features.json`](./features.json) | Feature checklist |
| [`AGENTS.md`](./AGENTS.md) | Dev quick start |

---

## Suggested next work

1. Tasks endpoint scoping (`GET /meetings/{id}/tasks`).
2. Jira live / real-time ASR (deferred).
