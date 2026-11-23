from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response

from registry.api.schemata import (
    ErrorResponse,
    ProjectCreate,
    ProjectId,
    ProjectPatch,
    ProjectResponse,
    patch_to_domain,
)
from registry.services.project_service import ProjectService

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def get_service(request: Request) -> ProjectService:
    return cast(ProjectService, request.app.state.project_service)


Service = Annotated[ProjectService, Depends(get_service)]
not_found: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
conflict: dict[int | str, dict[str, Any]] = {409: {"model": ErrorResponse}}


@router.post("", status_code=201, responses=conflict)
async def create_project(
    body: ProjectCreate, response: Response, service: Service
) -> ProjectResponse:
    project = await service.create(body.to_domain())
    response.headers["Location"] = f"/projects/{project.id}"
    return ProjectResponse.model_validate(project)


@router.get("")
async def list_projects(service: Service) -> list[ProjectResponse]:
    return [ProjectResponse.model_validate(project) for project in await service.list()]


@router.get("/{id}", responses=not_found)
async def get_project(id: ProjectId, service: Service) -> ProjectResponse:
    return ProjectResponse.model_validate(await service.get(id))


@router.patch("/{id}", responses={**not_found, **conflict})
async def update_project(
    id: ProjectId, body: ProjectPatch, service: Service
) -> ProjectResponse:
    return ProjectResponse.model_validate(
        await service.update(id, patch_to_domain(body))
    )


@router.delete("/{id}", status_code=204, responses=not_found)
async def delete_project(id: ProjectId, service: Service) -> Response:
    await service.delete(id)
    return Response(status_code=204)


@router.post(
    "/{id}/sync",
    responses={
        **not_found,
        **conflict,
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def sync_project(id: ProjectId, service: Service) -> ProjectResponse:
    return ProjectResponse.model_validate(await service.sync(id))
