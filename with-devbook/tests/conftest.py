from collections.abc import Callable, Iterator

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import HttpUrl, SecretStr

from registry.main import create_app
from registry.settings import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    database_path = tmp_path / "projects.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    command.upgrade(Config("alembic.ini"), "head")
    return Settings(
        _env_file=None,
        database_path=database_path,
        gitlab_url=HttpUrl("https://gitlab.example/gitlab"),
        gitlab_token=SecretStr("test-token"),
        gitlab_timeout_seconds=1.0,
    )


@pytest.fixture
def gitlab_reply() -> dict[str, object]:
    return {
        "id": 123,
        "name": "Renamed",
        "path_with_namespace": "other/renamed",
        "web_url": "https://gitlab.example/gitlab/other/renamed",
        "default_branch": None,
    }


@pytest.fixture
def gitlab_handler() -> Callable[[httpx.Request], httpx.Response]:
    def unexpected_call(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected GitLab call to {request.url}")

    return unexpected_call


@pytest.fixture
def client(settings, gitlab_handler) -> Iterator[TestClient]:
    app = create_app(settings, gitlab_transport=httpx.MockTransport(gitlab_handler))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def payload() -> dict[str, object]:
    return {
        "gitlab_project_id": 123,
        "name": "Registry",
        "path_with_namespace": "team/registry",
        "web_url": "https://gitlab.example/gitlab/team/registry",
        "default_branch": "main",
    }


@pytest.fixture
def project(client, payload) -> dict:
    response = client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()
