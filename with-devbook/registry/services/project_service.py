from collections.abc import Callable
from typing import Protocol

from registry.database.uow import UnitOfWork
from registry.domain.exceptions import ProjectChangedError, ProjectNotFoundError
from registry.domain.models import (
    Project,
    ProjectChanges,
    ProjectFields,
    ProjectMetadata,
)


class GitLabProjects(Protocol):
    async def fetch_project(self, gitlab_project_id: int) -> ProjectMetadata: ...


def require_project(project: Project | None) -> Project:
    if project is None:
        raise ProjectNotFoundError("Project does not exist")
    return project


class ProjectService:
    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], gitlab: GitLabProjects
    ) -> None:
        self._uow_factory = uow_factory
        self._gitlab = gitlab

    async def create(self, data: ProjectFields) -> Project:
        async with self._uow_factory() as uow:
            project = await uow.projects.add(data)
            await uow.commit()
            return project

    async def get(self, project_id: int) -> Project:
        async with self._uow_factory() as uow:
            return require_project(await uow.projects.get(project_id))

    async def list(self) -> list[Project]:
        async with self._uow_factory() as uow:
            return await uow.projects.list()

    async def update(self, project_id: int, changes: ProjectChanges) -> Project:
        async with self._uow_factory() as uow:
            if not changes:
                return require_project(await uow.projects.get(project_id))
            project = require_project(await uow.projects.update(project_id, changes))
            await uow.commit()
            return project

    async def delete(self, project_id: int) -> None:
        async with self._uow_factory() as uow:
            if not await uow.projects.delete(project_id):
                raise ProjectNotFoundError("Project does not exist")
            await uow.commit()

    async def sync(self, project_id: int) -> Project:
        async with self._uow_factory() as uow:
            project = require_project(await uow.projects.get(project_id))
            # Release the read transaction before waiting on GitLab.
            await uow.rollback()
            metadata = await self._gitlab.fetch_project(project.gitlab_project_id)
            changes: ProjectChanges = {
                "name": metadata["name"],
                "path_with_namespace": metadata["path_with_namespace"],
                "web_url": metadata["web_url"],
                "default_branch": metadata["default_branch"],
            }
            updated = await uow.projects.update(
                project_id, changes, revision=project.revision
            )
            if updated is None:
                require_project(await uow.projects.get(project_id))
                raise ProjectChangedError("Project changed during synchronization")
            await uow.commit()
            return updated
