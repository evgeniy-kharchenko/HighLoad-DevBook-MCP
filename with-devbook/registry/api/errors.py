import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from registry.adapters.exceptions import (
    GitLabConfigurationError,
    HTTPAdapterError,
    HTTPTimeoutError,
)
from registry.api.schemata import ErrorResponse
from registry.domain.exceptions import (
    DuplicateProjectError,
    ProjectChangedError,
    ProjectNotFoundError,
)

logger = logging.getLogger(__name__)

exception_status = {
    ProjectNotFoundError: (404, "project_not_found"),
    DuplicateProjectError: (409, "duplicate_project"),
    ProjectChangedError: (409, "project_changed"),
    HTTPAdapterError: (502, "gitlab_error"),
    GitLabConfigurationError: (503, "gitlab_not_configured"),
    HTTPTimeoutError: (504, "gitlab_timeout"),
}


def error_response(
    status: int, code: str, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    payload = ErrorResponse(code=code, message=message, details=details or {})
    return JSONResponse(status_code=status, content=payload.model_dump())


async def expected_error(request: Request, exc: Exception) -> JSONResponse:
    status, code = exception_status[type(exc)]
    if status >= 500:
        logger.warning("GitLab operation failed", extra={"error_code": code})
    return error_response(status, code, str(exc))


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = [
        {"location": error["loc"], "type": error["type"], "message": error["msg"]}
        for error in cast(RequestValidationError, exc).errors()
    ]
    return error_response(
        422, "validation_error", "Invalid request", {"errors": errors}
    )


async def http_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(HTTPException, exc)
    response = error_response(
        exc.status_code, f"http_{exc.status_code}", str(exc.detail)
    )
    response.headers.update(exc.headers or {})
    return response


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "internal_error", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    for exception in exception_status:
        app.add_exception_handler(exception, expected_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(Exception, unexpected_error)
