from contextlib import asynccontextmanager

from fastapi import FastAPI

from meeting_assistant.api.routes import admin, approvals, batch, health, retrieval, workflows
from meeting_assistant.bootstrap import bootstrap_container
from meeting_assistant.core.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None)
    app.state.container = bootstrap_container(settings)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Meeting Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(batch.router, prefix="/api/v1")
    app.include_router(workflows.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(retrieval.router, prefix="/api/v1")
    app.include_router(admin.router)
    return app
