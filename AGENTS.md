# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

Single-service Python **Meeting Assistant** API (modular monolith) plus a **Vite+React frontend** in `frontend/`. Default dev stack: SQLite + in-process queue/embeddings + heuristic planner + stub tools.

**Phase 15 (planned):** Proper login UI — email/password + Google Sign-In. Replaces browser API-key panel; Secret Manager keys remain for ops/Postman only. See [`progress.md`](./progress.md) Phase 15 and ADR-17 in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

### Services

| Service | Command | Port |
|---------|---------|------|
| FastAPI (Uvicorn) | `uv run uvicorn meeting_assistant.main:app --reload` | 8000 |

Use tmux for long-running dev server sessions (e.g. session name `meeting-assistant-api`).

### Dependencies

- **Python** ≥ 3.12 (system Python is fine; `uv` manages `.venv`)
- **uv** package manager (`~/.local/bin/uv`; should be on PATH in Cloud Agent VMs)

Install/sync deps (see README):

```bash
uv sync --extra dev
```

### Common commands

| Task | Command |
|------|---------|
| Install deps | `uv sync --extra dev` |
| Run server | `uv run uvicorn meeting_assistant.main:app --reload` |
| Run frontend | `cd frontend && npm install && npm run dev` |
| Run tests | `uv run pytest` |
| Docker Compose stack | `cp .env.compose.example .env.compose && make compose-up` |
| API docs | http://127.0.0.1:8000/docs |
| Health check | `curl http://127.0.0.1:8000/health` |
| Readiness check | `curl http://127.0.0.1:8000/ready` |

### Linting

```bash
uv run ruff check src tests
uv run mypy src/meeting_assistant
uv run pytest
```

CI runs ruff, mypy, pytest (SQLite), and a Postgres migration smoke job on pull requests.

### Optional secrets

Not required for core E2E flows (transcript text + heuristic planner):

- `MEETING_ASSISTANT_LLM_OPENAI_API_KEY` — hosted LLM planner
- `MEETING_ASSISTANT_ASR_OPENAI_API_KEY` — audio transcription via `source_uri`

### Hello-world verification

After starting the server, POST a batch meeting with `transcript_text` to `/api/v1/meetings/batch`, then hit search/tasks/decisions/query endpoints. See `tests/test_api.py::test_batch_ingestion_and_retrieval` for the canonical flow.

### Production auth (GCP)

When `AUTH_ENABLED=true` (set in `deploy/.env.prod`):

- `/health` and `/ready` remain **public** (no key required).
- Browser users: **JWT** from email/password or Google login (Phase 15 — `POST /auth/login/email`, `/auth/google/connect`).
- Ops / Postman / scripts: **`X-API-Key`** or legacy `POST /auth/login` with API key from Secret Manager.
- Secret Manager `meeting-assistant-api-keys` format: `user_external_id:api_key` — **not for end-user browser login** after Phase 15.

Postman example:

```bash
curl -H "X-API-Key: your-postman-secret" \
  -H "Content-Type: application/json" \
  -d '{"user_external_id":"indra",...}' \
  https://your-api.run.app/api/v1/meetings/batch
```

Create/update the secret:

```bash
echo -n 'indra:your-postman-secret' | gcloud secrets versions add meeting-assistant-api-keys --data-file=-
```

### Notes

- SQLite DB file defaults to `./meeting_assistant.db` (auto-created on startup).
- Calendar tool actions return `approval_required` in stub mode; live Google Calendar requires approve flow. Email/Slack use stub providers locally; SendGrid/webhook on GCP.

### Feature development

Track work in [`features.json`](./features.json) (`pass` / `not_started`) and read [`progress.md`](./progress.md) for roadmap context.

**One feature at a time.** Before starting implementation, pick exactly one feature with `"status": "not_started"` from `features.json`. Do not begin another feature until the current one is fully done or you explicitly hand off with it still incomplete. If the user's request spans multiple features, finish the first before moving on.

**Exit criteria — all checks must pass.** A feature is not complete until every step below succeeds. Do not mark the feature `pass` or stop working on it early.

1. Implement the feature (code, config, tests as needed).
2. Run the full quality gate and fix failures until clean:

```bash
uv run ruff check src tests
uv run mypy src/meeting_assistant
uv run pytest
```

3. For integrations that need live verification (e.g. Slack on GCP), run the manual check described in the feature's `description` and confirm it works.
4. Only then update `features.json` for that feature:
   - Set `"status": "pass"`
   - Set `"evidence"` — what was verified (tests, commands, live check)
   - Set `"testedAt"` — today's date (`YYYY-MM-DD`)
5. Update [`progress.md`](./progress.md) if the milestone is significant.

If any test or lint step fails, keep working on the same feature until they all pass. Never set `"status": "pass"` on failing tests.
