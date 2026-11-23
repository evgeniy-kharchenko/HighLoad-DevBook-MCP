from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


class ProjectMetadata(TypedDict):
    name: str
    path_with_namespace: str
    web_url: str
    default_branch: str | None


class ProjectFields(ProjectMetadata):
    gitlab_project_id: int


class ProjectChanges(TypedDict, total=False):
    name: str
    path_with_namespace: str
    web_url: str
    default_branch: str | None
    gitlab_project_id: int


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    gitlab_project_id: int
    name: str
    path_with_namespace: str
    web_url: str
    default_branch: str | None
    created_at: datetime
    updated_at: datetime
    revision: int
