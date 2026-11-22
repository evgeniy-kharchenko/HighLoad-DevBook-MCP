import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

from registry import GitLab, Registry

PROJECT = {
    "gitlab_project_id": 123,
    "name": "Original",
    "path_with_namespace": "team/original",
    "web_url": "https://gitlab.example/team/original",
    "default_branch": "main",
}
REMOTE = {
    "name": "Updated",
    "path_with_namespace": "team/updated",
    "web_url": "https://gitlab.example/team/updated",
    "default_branch": None,
}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(dir="."))
        self.database = Path(directory) / "tests.sqlite3"
        self.gitlab = GitLab("https://gitlab.example/gitlab/", "test-token")
        self.app = validator(Registry(self.database, self.gitlab))

    def request(self, method, path, data=None, *, raw=None, content_type="application/json"):
        environ = {}
        setup_testing_defaults(environ)
        payload = raw if raw is not None else (json.dumps(data).encode() if data is not None else b"")
        environ.update(
            REQUEST_METHOD=method,
            PATH_INFO=path,
            QUERY_STRING="",
            CONTENT_TYPE=content_type,
            CONTENT_LENGTH=str(len(payload)),
        )
        environ["wsgi.input"] = io.BytesIO(payload)
        result = {}

        def start_response(status, headers, exc_info=None):
            result["status"] = int(status.split()[0])
            result["headers"] = dict(headers)
            return self.fail

        response = self.app(environ, start_response)
        try:
            body = b"".join(response)
        finally:
            response.close()
        return result["status"], json.loads(body) if body else None, result["headers"]

    def create(self):
        status, project, headers = self.request("POST", "/projects", PROJECT)
        self.assertEqual(status, 201)
        self.assertEqual(project, {**PROJECT, **{key: project[key] for key in (
            "id", "created_at", "updated_at",
        )}})
        self.assertEqual(project["created_at"], project["updated_at"])
        self.assertEqual(headers["Location"], f'/projects/{project["id"]}')
        return headers["Location"], project

    def test_crud_and_persistence(self):
        self.assertEqual(self.request("GET", "/projects")[:2], (200, []))
        path, project = self.create()
        self.app = validator(Registry(self.database, self.gitlab))
        self.assertEqual(self.request("GET", path)[:2], (200, project))
        self.assertEqual(self.request("GET", "/projects")[:2], (200, [project]))
        with patch("registry.timestamp", return_value="2026-01-01T00:00:00+00:00"):
            status, updated, _ = self.request("PATCH", path, {"name": "New", "default_branch": None})
        self.assertEqual(status, 200)
        self.assertEqual(updated, {
            **project, "name": "New", "default_branch": None,
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        self.assertEqual(self.request("DELETE", path)[:2], (204, None))
        self.assertEqual(self.request("GET", "/projects")[:2], (200, []))

    def test_conflict_and_missing_project(self):
        path, _ = self.create()
        self.assertEqual(self.request("POST", "/projects", PROJECT)[0], 409)
        _, other, headers = self.request("POST", "/projects", {**PROJECT, "gitlab_project_id": 456})
        self.assertEqual(self.request("PATCH", headers["Location"], {"gitlab_project_id": 123})[0], 409)
        self.assertEqual(self.request("GET", headers["Location"])[1], other)
        self.request("DELETE", path)
        for method, suffix, data in (
            ("GET", "", None), ("PATCH", "", {"name": "New"}),
            ("DELETE", "", None), ("POST", "/sync", None),
        ):
            with self.subTest(method=method, suffix=suffix):
                self.assertEqual(self.request(method, path + suffix, data)[0], 404)

    def test_invalid_requests(self):
        for data in ({}, {**PROJECT, "gitlab_project_id": True}, {**PROJECT, "id": 1},
                     {**PROJECT, "name": None}, {**PROJECT, "name": "\ud800"}):
            with self.subTest(data=data):
                self.assertEqual(self.request("POST", "/projects", data)[0], 400)
        self.assertEqual(self.request("POST", "/projects", raw=b"{")[0], 400)
        self.assertEqual(self.request("POST", "/projects", raw=b"x" * 65537)[0], 413)
        self.assertEqual(self.request("POST", "/projects", PROJECT, content_type="text/plain")[0], 415)
        self.assertEqual(self.request("DELETE", "/projects")[2]["Allow"], "GET, POST")

    def test_sync_uses_configured_gitlab_and_persists_metadata(self):
        path, project = self.create()
        response = io.BytesIO(json.dumps({**REMOTE, "id": 123, "visibility": "private"}).encode())
        with patch.object(self.gitlab.opener, "open", return_value=response) as open_url:
            status, synced, _ = self.request("POST", path + "/sync")
        self.assertEqual(status, 200)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://gitlab.example/gitlab/api/v4/projects/123")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Private-token"), "test-token")
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 5})
        self.assertEqual(synced, {**project, **REMOTE, "updated_at": synced["updated_at"]})
        self.assertEqual(self.request("GET", path)[:2], (200, synced))

    def test_failed_sync_preserves_project(self):
        path, project = self.create()
        for error in (URLError("timeout"), HTTPError("https://gitlab.example", 302, "", {}, None)):
            with patch.object(self.gitlab.opener, "open", side_effect=error):
                self.assertEqual(self.request("POST", path + "/sync")[0], 502)
        with patch.object(self.gitlab.opener, "open", return_value=io.BytesIO(b'{"name": "New"}')):
            self.assertEqual(self.request("POST", path + "/sync")[0], 502)
        self.gitlab.token = None
        self.assertEqual(self.request("POST", path + "/sync")[0], 503)
        self.assertEqual(self.request("GET", path)[:2], (200, project))

    def test_sync_checks_id_after_remote_request(self):
        path, _ = self.create()

        def change_id(_gitlab_id):
            self.assertEqual(self.request("PATCH", path, {"gitlab_project_id": 456})[0], 200)
            return REMOTE

        with patch.object(self.gitlab, "project", side_effect=change_id):
            self.assertEqual(self.request("POST", path + "/sync")[0], 409)
        self.assertEqual(self.request("GET", path)[1]["name"], PROJECT["name"])


if __name__ == "__main__":
    unittest.main()
