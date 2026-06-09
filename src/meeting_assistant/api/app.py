from contextlib import asynccontextmanager

from fastapi import FastAPI

from meeting_assistant.api.routes import batch, health, retrieval
from meeting_assistant.bootstrap import bootstrap_container


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = bootstrap_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meeting Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(batch.router, prefix="/api/v1")
    app.include_router(retrieval.router, prefix="/api/v1")
    return app
