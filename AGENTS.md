# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

Single-service Python **Meeting Assistant** API (modular monolith). No frontend, Docker Compose, or external databases required for local development. Default stack: SQLite + in-process queue/embeddings + heuristic planner.

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
| Run tests | `uv run pytest` |
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

### Notes

- SQLite DB file defaults to `./meeting_assistant.db` (auto-created on startup).
- Calendar tool actions return `approval_required`; email tool executes in stub mode — both are expected.
