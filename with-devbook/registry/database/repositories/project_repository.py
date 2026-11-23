import sqlite3
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from registry.database.orm import ProjectRow
from registry.domain.exceptions import DuplicateProjectError
from registry.domain.models import Project, ProjectChanges, ProjectFields


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: ProjectFields) -> Project:
        now = datetime.now(UTC)
        project = ProjectRow(**data, created_at=now, updated_at=now, revision=1)
        self._session.add(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            self._translate_integrity_error(exc)
            raise
        return project.to_domain()

    async def get(self, project_id: int) -> Project | None:
        row = await self._session.get(ProjectRow, project_id, populate_existing=True)
        return row.to_domain() if row else None

    async def list(self) -> list[Project]:
        rows = await self._session.scalars(select(ProjectRow).order_by(ProjectRow.id))
        return [row.to_domain() for row in rows]

    async def update(
        self, project_id: int, changes: ProjectChanges, *, revision: int | None = None
    ) -> Project | None:
        statement = update(ProjectRow).where(ProjectRow.id == project_id)
        if revision is not None:
            statement = statement.where(ProjectRow.revision == revision)
        statement = statement.values(
            **changes,
            updated_at=datetime.now(UTC),
            revision=ProjectRow.revision + 1,
        ).returning(ProjectRow)
        try:
            result = await self._session.scalars(
                statement, execution_options={"populate_existing": True}
            )
        except IntegrityError as exc:
            self._translate_integrity_error(exc)
            raise
        row = result.one_or_none()
        return row.to_domain() if row else None

    async def delete(self, project_id: int) -> bool:
        result = await self._session.scalars(
            delete(ProjectRow)
            .where(ProjectRow.id == project_id)
            .returning(ProjectRow.id)
        )
        return result.one_or_none() is not None

    @staticmethod
    def _translate_integrity_error(exc: IntegrityError) -> None:
        if (
            getattr(exc.orig, "sqlite_errorcode", None)
            == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        ):
            raise DuplicateProjectError("GitLab project is already registered") from exc
