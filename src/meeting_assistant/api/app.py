from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from meeting_assistant.api.auth import require_auth
from meeting_assistant.api.rate_limit import configure_limiter
from meeting_assistant.api.routes import (
    admin,
    approvals,
    auth_routes,
    batch,
    health,
    integrations,
    ops,
    retrieval,
    workflows,
)
from meeting_assistant.bootstrap import bootstrap_container
from meeting_assistant.core.config import Settings
from meeting_assistant.core.logging import RequestContextMiddleware, configure_logging
from meeting_assistant.core.telemetry import configure_telemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings or Settings()
    configure_logging(settings)
    app.state.container = bootstrap_container(settings)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(
        title="Meeting Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.limiter = configure_limiter(resolved_settings)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(RequestContextMiddleware, service_name=resolved_settings.otel_service_name)

    if resolved_settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    protected_dependencies = [Depends(require_auth)] if resolved_settings.auth_enabled else []

    app.include_router(health.router)
    app.include_router(auth_routes.router, prefix="/api/v1")
    app.include_router(batch.router, prefix="/api/v1", dependencies=protected_dependencies)
    app.include_router(workflows.router, prefix="/api/v1", dependencies=protected_dependencies)
    app.include_router(approvals.router, prefix="/api/v1", dependencies=protected_dependencies)
    app.include_router(retrieval.router, prefix="/api/v1", dependencies=protected_dependencies)
    app.include_router(integrations.router, prefix="/api/v1")
    app.include_router(admin.router, dependencies=protected_dependencies)
    app.include_router(ops.router, dependencies=protected_dependencies)

    configure_telemetry(resolved_settings, app)
    return app
