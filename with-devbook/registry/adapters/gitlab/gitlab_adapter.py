import asyncio
from typing import Annotated

import httpx
from pydantic import BaseModel, HttpUrl, StringConstraints, ValidationError

from registry.adapters.exceptions import (
    GitLabConfigurationError,
    HTTPAdapterError,
    HTTPTimeoutError,
)
from registry.domain.models import ProjectMetadata

NonEmptyString = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]


class GitLabProjectPayload(BaseModel):
    name: NonEmptyString
    path_with_namespace: NonEmptyString
    web_url: HttpUrl
    default_branch: NonEmptyString | None


class GitLabAdapter:
    def __init__(
        self, client: httpx.AsyncClient, token: str | None, timeout: float
    ) -> None:
        self._client = client
        self._token = token
        self._timeout = timeout

    async def fetch_project(self, gitlab_project_id: int) -> ProjectMetadata:
        if not self._token:
            raise GitLabConfigurationError("GitLab access token is not configured")

        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.get(
                    f"api/v4/projects/{gitlab_project_id}",
                    headers={"PRIVATE-TOKEN": self._token},
                )
            response.raise_for_status()
            payload = GitLabProjectPayload.model_validate_json(response.content)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise HTTPTimeoutError("GitLab request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPAdapterError("GitLab returned an unsuccessful status") from exc
        except (httpx.RequestError, ValidationError) as exc:
            raise HTTPAdapterError(
                "GitLab did not provide valid project metadata"
            ) from exc

        return {
            "name": payload.name,
            "path_with_namespace": payload.path_with_namespace,
            "web_url": str(payload.web_url),
            "default_branch": payload.default_branch,
        }
