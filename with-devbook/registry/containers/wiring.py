from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import httpx
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from registry.adapters.gitlab.gitlab_adapter import GitLabAdapter
from registry.database.uow import UnitOfWork
from registry.services.project_service import ProjectService
from registry.settings import Settings


def reveal_token(settings: Settings) -> str | None:
    token = settings.gitlab_token
    return token.get_secret_value() if token else None


class RegistryContainer(containers.DeclarativeContainer):
    session_factory: providers.Dependency[async_sessionmaker[AsyncSession]] = (
        providers.Dependency()
    )
    http_client: providers.Dependency[httpx.AsyncClient] = providers.Dependency()
    settings: providers.Dependency[Settings] = providers.Dependency()

    uow_factory = providers.Factory(partial, UnitOfWork, session_factory)
    gitlab = providers.Singleton(
        GitLabAdapter,
        client=http_client,
        token=providers.Callable(reveal_token, settings),
        timeout=settings.provided.gitlab_timeout_seconds,
    )
    project_service = providers.Factory(
        ProjectService, uow_factory=uow_factory, gitlab=gitlab
    )


@asynccontextmanager
async def project_service_scope(
    config: Settings, gitlab_transport: httpx.AsyncBaseTransport | None
) -> AsyncIterator[ProjectService]:
    engine = create_async_engine(config.database_url, hide_parameters=True)
    try:
        async with httpx.AsyncClient(
            base_url=str(config.gitlab_url).rstrip("/") + "/",
            timeout=config.gitlab_timeout_seconds,
            follow_redirects=False,
            transport=gitlab_transport,
        ) as client:
            container = RegistryContainer(
                session_factory=providers.Object(async_sessionmaker(engine)),
                http_client=providers.Object(client),
                settings=providers.Object(config),
            )
            yield container.project_service()
    finally:
        await engine.dispose()
