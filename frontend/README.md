# Meeting Assistant Frontend

Vite + React + TypeScript web app for the Meeting Assistant API.

## Screens

- **Upload** — paste transcript or upload audio (`POST /api/v1/meetings/batch`, `/batch/upload`)
- **Workflow** — poll workflow status and tool executions (`GET /api/v1/workflows/{id}`)
- **Search** — semantic search across meetings, transcript chunks, and decisions with cursor pagination
- **Ask** — RAG query with citations and retrieved context panel
- **Approvals** — list and approve/reject pending tool actions
- **Integrations** — connect Slack workspace, Google calendar read access, and email notification prefs; actions appear as **Meeting Assistant**

## Local development

1. Start the API (from repo root):

```bash
uv sync --extra dev
uv run uvicorn meeting_assistant.main:app --reload
```

2. Install and run the frontend:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173. The API enables CORS for `http://localhost:5173` by default via `MEETING_ASSISTANT_CORS_ORIGINS`.

## Configuration

Copy `.env.example` to `.env`. Auth session is managed via `/login` when the API has auth enabled.

| Variable | Purpose |
|----------|---------|
| `VITE_API_BASE_URL` | API origin (default `http://127.0.0.1:8000`) |
| `VITE_USER_EXTERNAL_ID` | Default user ID when auth is disabled |
| `VITE_USER_EMAIL` | Default email when auth is disabled |

When `MEETING_ASSISTANT_AUTH_ENABLED=true`, sign in at `/login` with email/password or Google. Set `MEETING_ASSISTANT_AUTH_JWT_SECRET` on the API. For local dev without a real login provider, enable `MEETING_ASSISTANT_AUTH_LOGIN_ALLOW_DEV=true`. Ops scripts can still exchange an API key at `POST /api/v1/auth/login`; that form is not in the browser UI.

## Integrations settings

Route: `/settings/integrations`

| Card | User action | Outbound identity |
|------|-------------|-------------------|
| Slack | OAuth workspace install; pick allowed channels | **Meeting Assistant** bot |
| Google | OAuth read access; pick readable calendars | Events from **assistant calendar** |
| Email | Set notification addresses (no OAuth) | **Meeting Assistant** branded sender |

OAuth providers redirect back to the frontend after connect. Upload at least one meeting first so your user record exists before connecting.

See [`ARCHITECTURE.md`](../ARCHITECTURE.md) ADR-15 and `integrations-settings-ui` in [`features.json`](../features.json).

## Login (Phase 15)

Routes: `/login`, `/register`

| Method | User action |
|--------|-------------|
| Email + password | Register or sign in → JWT stored in `localStorage` |
| Google | Sign in with Google → OAuth (login scopes only) → JWT in URL fragment on redirect |

When `MEETING_ASSISTANT_AUTH_ENABLED=true`, unauthenticated users are redirected to `/login`. The sidebar shows signed-in email and Sign out — no API key fields.

Google login OAuth is **separate** from Settings → Integrations Google connect (calendar read). See ADR-17 in [`ARCHITECTURE.md`](../ARCHITECTURE.md).

## Build

```bash
npm run build
npm run preview
```

Static output is in `frontend/dist/` — deploy to Vercel, Cloud Run (nginx), or any static host.
