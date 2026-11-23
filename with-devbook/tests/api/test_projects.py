from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from registry.main import create_app


def test_create_project(client, payload):
    response = client.post("/projects", json=payload)

    assert response.status_code == 201
    project = response.json()
    assert response.headers["Location"] == f"/projects/{project['id']}"
    assert project == {
        **payload,
        "id": project["id"],
        "created_at": project["created_at"],
        "updated_at": project["created_at"],
    }
    assert datetime.fromisoformat(project["created_at"]).utcoffset() == timedelta(0)


def test_get_project_persists_across_app_instances(project, settings):
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json() == project


def test_list_projects(client, project, payload):
    second = client.post("/projects", json={**payload, "gitlab_project_id": 456})
    response = client.get("/projects")

    assert second.status_code == 201
    assert response.status_code == 200
    assert response.json() == [project, second.json()]


def test_patch_preserves_omitted_fields(client, project):
    url = f"/projects/{project['id']}"
    changes = {
        "gitlab_project_id": 789,
        "web_url": "https://gitlab.example/gitlab/team/new",
        "default_branch": None,
    }

    response = client.patch(url, json=changes)

    assert response.status_code == 200
    updated = response.json()
    assert datetime.fromisoformat(updated["updated_at"]) > datetime.fromisoformat(
        project["updated_at"]
    )
    assert updated == {**project, **changes, "updated_at": updated["updated_at"]}
    assert client.get(url).json() == updated


def test_empty_patch_preserves_timestamps(client, project):
    response = client.patch(f"/projects/{project['id']}", json={})

    assert response.status_code == 200
    assert response.json() == project


def test_delete_project(client, project):
    url = f"/projects/{project['id']}"

    response = client.delete(url)

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(url).status_code == 404
    assert client.get("/projects").json() == []


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/projects/99", None),
        ("PATCH", "/projects/99", {}),
        ("DELETE", "/projects/99", None),
        ("POST", "/projects/99/sync", None),
    ],
)
def test_unknown_project(client, method, url, body):
    response = client.request(method, url, json=body)

    assert response.status_code == 404
    assert response.json() == {
        "code": "project_not_found",
        "message": "Project does not exist",
        "details": {},
    }


def test_duplicate_create_is_rejected(client, project, payload):
    response = client.post("/projects", json=payload)

    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_project"
    assert client.get("/projects").json() == [project]


def test_duplicate_patch_rolls_back(client, project, payload):
    second = client.post("/projects", json={**payload, "gitlab_project_id": 456}).json()
    response = client.patch(
        f"/projects/{second['id']}", json={"gitlab_project_id": 123, "name": "Changed"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_project"
    assert client.get("/projects").json() == [project, second]


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"web_url": "ftp://gitlab.example/a"},
        {"gitlab_project_id": True},
        {"gitlab_project_id": 2**63},
        {"id": 999},
    ],
)
def test_invalid_create_returns_error_envelope(client, payload, changes):
    response = client.post("/projects", json={**payload, **changes})

    assert response.status_code == 422
    error = response.json()
    assert error["code"] == "validation_error"
    assert error["details"]["errors"][0]["location"] == ["body", next(iter(changes))]


@pytest.mark.parametrize(
    "changes", [{"name": None}, {"gitlab_project_id": 0}, {"id": 999}]
)
def test_invalid_patch_leaves_project_intact(client, project, changes):
    url = f"/projects/{project['id']}"

    response = client.patch(url, json=changes)

    assert response.status_code == 422
    assert client.get(url).json() == project
