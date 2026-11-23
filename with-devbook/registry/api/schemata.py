from datetime import datetime
from typing import Annotated, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    with_config,
)
from typing_extensions import TypedDict

from registry.domain.models import ProjectChanges, ProjectFields

MAX_SQLITE_ID = 2**63 - 1
ProjectId = Annotated[int, Field(gt=0, le=MAX_SQLITE_ID)]
GitLabProjectId = Annotated[int, Field(strict=True, gt=0, le=MAX_SQLITE_ID)]
NonEmptyString = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gitlab_project_id: GitLabProjectId
    name: NonEmptyString
    path_with_namespace: NonEmptyString
    web_url: HttpUrl
    default_branch: NonEmptyString | None = None

    def to_domain(self) -> ProjectFields:
        return {
            "gitlab_project_id": self.gitlab_project_id,
            "name": self.name,
            "path_with_namespace": self.path_with_namespace,
            "web_url": str(self.web_url),
            "default_branch": self.default_branch,
        }


@with_config(ConfigDict(extra="forbid"))
class ProjectPatch(TypedDict, total=False):
    gitlab_project_id: GitLabProjectId
    name: NonEmptyString
    path_with_namespace: NonEmptyString
    web_url: HttpUrl
    default_branch: NonEmptyString | None


def patch_to_domain(body: ProjectPatch) -> ProjectChanges:
    data = dict(body)
    if "web_url" in body:
        data["web_url"] = str(body["web_url"])
    return cast(ProjectChanges, data)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gitlab_project_id: int
    name: str
    path_with_namespace: str
    web_url: str
    default_branch: str | None
    created_at: datetime
    updated_at: datetime


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object]
