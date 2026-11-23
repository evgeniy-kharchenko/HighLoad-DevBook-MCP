from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from registry.api.errors import register_error_handlers
from registry.api.projects import router
from registry.containers.wiring import project_service_scope
from registry.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    gitlab_transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else Settings()
        async with project_service_scope(config, gitlab_transport) as service:
            app.state.project_service = service
            yield

    app = FastAPI(title="GitLab Project Registry", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
