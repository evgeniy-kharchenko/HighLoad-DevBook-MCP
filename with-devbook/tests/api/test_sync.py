import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from registry.main import create_app


@pytest.fixture
def gitlab_handler(gitlab_reply):
    def reply(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == "https://gitlab.example/gitlab/api/v4/projects/123"
        assert request.headers["PRIVATE-TOKEN"] == "test-token"
        return httpx.Response(200, json=gitlab_reply)

    return reply


def test_sync_refreshes_metadata(client, project, gitlab_reply):
    url = f"/projects/{project['id']}"

    response = client.post(f"{url}/sync")

    assert response.status_code == 200
    updated = response.json()
    assert updated["updated_at"] > project["updated_at"]
    metadata = {key: value for key, value in gitlab_reply.items() if key != "id"}
    assert updated == {**project, **metadata, "updated_at": updated["updated_at"]}
    assert client.get(url).json() == updated


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("redirect", 502, "gitlab_error"),
        ("status", 502, "gitlab_error"),
        ("malformed", 502, "gitlab_error"),
        ("missing_fields", 502, "gitlab_error"),
        ("network", 502, "gitlab_error"),
        ("timeout", 504, "gitlab_timeout"),
        ("budget", 504, "gitlab_timeout"),
        ("missing_token", 503, "gitlab_not_configured"),
    ],
)
def test_failed_sync_leaves_project_intact(settings, payload, case, status, code):
    calls = []

    async def reply(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        if case == "redirect":
            return httpx.Response(
                302, headers={"Location": "https://elsewhere.example"}
            )
        if case == "status":
            return httpx.Response(403, text="private upstream response")
        if case == "malformed":
            return httpx.Response(200, text="private upstream response")
        if case == "missing_fields":
            return httpx.Response(200, json={"name": "Changed"})
        if case == "network":
            raise httpx.ConnectError("private upstream response", request=request)
        if case == "timeout":
            raise httpx.ReadTimeout("private upstream response", request=request)
        if case == "budget":
            await asyncio.sleep(2)
            return httpx.Response(200)
        pytest.fail("GitLab must not be called without credentials")

    if case == "budget":
        settings.gitlab_timeout_seconds = 0.02
    if case == "missing_token":
        settings.gitlab_token = None
    app = create_app(settings, gitlab_transport=httpx.MockTransport(reply))
    with TestClient(app) as client:
        project = client.post("/projects", json=payload).json()
        url = f"/projects/{project['id']}"
        response = client.post(f"{url}/sync")

        assert response.status_code == status
        assert response.json()["code"] == code
        assert "private upstream response" not in response.text
        assert len(calls) == (0 if case == "missing_token" else 1)
        assert client.get(url).json() == project


@pytest.mark.parametrize(("method", "status"), [("PATCH", 409), ("DELETE", 404)])
def test_sync_does_not_overwrite_concurrent_mutation(
    settings, payload, gitlab_reply, method, status
):
    started = Event()
    release = Event()

    async def reply(request: httpx.Request) -> httpx.Response:
        started.set()
        assert await asyncio.to_thread(release.wait, 5)
        return httpx.Response(200, json=gitlab_reply)

    settings.gitlab_timeout_seconds = 6.0
    app = create_app(settings, gitlab_transport=httpx.MockTransport(reply))
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        project = client.post("/projects", json=payload).json()
        url = f"/projects/{project['id']}"
        sync = executor.submit(client.post, f"{url}/sync")

        try:
            assert started.wait(5)
            if method == "PATCH":
                mutation = client.patch(url, json={"gitlab_project_id": 456})
                assert mutation.status_code == 200
            else:
                assert client.delete(url).status_code == 204
        finally:
            release.set()

        assert sync.result(timeout=5).status_code == status
        current = client.get(url)
        if method == "PATCH":
            assert current.json() == mutation.json()
        else:
            assert current.status_code == 404
