from datetime import UTC, datetime

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from registry.domain.models import Project


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("gitlab_project_id > 0", name="ck_projects_gitlab_id_positive"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    gitlab_project_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]
    path_with_namespace: Mapped[str]
    web_url: Mapped[str]
    default_branch: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    revision: Mapped[int]

    def to_domain(self) -> Project:
        return Project(
            id=self.id,
            gitlab_project_id=self.gitlab_project_id,
            name=self.name,
            path_with_namespace=self.path_with_namespace,
            web_url=self.web_url,
            default_branch=self.default_branch,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
        )
