"""WSGI service for storing and synchronizing GitLab projects."""

import json
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http import HTTPStatus
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from wsgiref.simple_server import make_server

FIELDS = ("gitlab_project_id", "name", "path_with_namespace", "web_url", "default_branch")
METADATA = FIELDS[1:]
MAX_BODY = 64 * 1024
MAX_GITLAB_BODY = 1024 * 1024
ITEM_PATH = re.compile(r"/projects/([1-9][0-9]{0,18})(/sync)?")
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gitlab_project_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    path_with_namespace TEXT NOT NULL,
    web_url TEXT NOT NULL,
    default_branch TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class APIError(Exception):
    def __init__(self, status, message, headers=()):
        super().__init__(message)
        self.status = status
        self.headers = headers


def validate(data, fields, *, partial=False):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    if set(data) - set(fields):
        raise ValueError("Unknown fields")
    required = set(fields) - {"default_branch"}
    if not partial and required - data.keys():
        raise ValueError("Missing required fields")
    for key, value in data.items():
        if key == "gitlab_project_id":
            if type(value) is not int or not 0 < value < 2**63:
                raise ValueError("gitlab_project_id must be a positive 64-bit integer")
        elif key == "default_branch" and value is None:
            continue
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        else:
            value.encode("utf-8")
    return data


def read_payload(environ, *, partial=False):
    if environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
        raise APIError(415, "Expected application/json")
    try:
        size = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise APIError(400, "Invalid Content-Length") from None
    if size > MAX_BODY:
        raise APIError(413, "Request body exceeds 64 KiB")
    if size < 0:
        raise APIError(400, "Invalid Content-Length")
    try:
        data = json.loads(environ["wsgi.input"].read(size).decode("utf-8"))
        return validate(data, FIELDS, partial=partial)
    except (ValueError, RecursionError) as error:
        raise APIError(400, str(error)) from None


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitLab:
    def __init__(self, base_url, token):
        parts = urlsplit(base_url)
        if (
            parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.query or parts.fragment
        ):
            raise ValueError("GITLAB_URL must be an HTTP(S) base URL without credentials")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = build_opener(NoRedirects())

    def project(self, gitlab_id):
        if not self.token:
            raise APIError(503, "GitLab access token is not configured")
        request = Request(
            f"{self.base_url}/api/v4/projects/{gitlab_id}",
            headers={"PRIVATE-TOKEN": self.token, "Accept": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                body = response.read(MAX_GITLAB_BODY + 1)
            if len(body) > MAX_GITLAB_BODY:
                raise ValueError("GitLab response too large")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Expected a GitLab project object")
            metadata = {key: data[key] for key in METADATA}
            return validate(metadata, METADATA)
        except HTTPError as error:
            error.close()
            raise APIError(502, "Could not retrieve valid project data from GitLab") from None
        except (OSError, HTTPException, ValueError, KeyError, RecursionError):
            raise APIError(502, "Could not retrieve valid project data from GitLab") from None


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def get_project(db, project_id):
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise APIError(404, "Project not found")
    return dict(project)


def update_project(db, project_id, changes, *, expected_gitlab_id=None):
    if not changes:
        return get_project(db, project_id)
    assignments = ", ".join(f"{field} = ?" for field in changes)
    sql = f"UPDATE projects SET {assignments}, updated_at = ? WHERE id = ?"
    params = [*changes.values(), timestamp(), project_id]
    if expected_gitlab_id is not None:
        sql += " AND gitlab_project_id = ?"
        params.append(expected_gitlab_id)
    updated = db.execute(sql, params)
    project = get_project(db, project_id)
    if not updated.rowcount:
        raise APIError(409, "GitLab project ID changed during synchronization")
    return project


class Registry:
    def __init__(self, database_path, gitlab):
        self.database_path = database_path
        self.gitlab = gitlab
        with closing(self.connect()) as db:
            db.execute(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.database_path)
        db.row_factory = sqlite3.Row
        return db

    def __call__(self, environ, start_response):
        headers = []
        try:
            with closing(self.connect()) as db, db:
                status, data, headers = self.dispatch(db, environ)
        except APIError as error:
            status, data, headers = error.status, {"error": str(error)}, list(error.headers)
        except sqlite3.IntegrityError as error:
            if error.sqlite_errorcode != sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                logging.exception("Database integrity error")
                status, data = 500, {"error": "Database operation failed"}
            else:
                status, data = 409, {"error": "GitLab project ID already exists"}
        except sqlite3.Error:
            logging.exception("Database operation failed")
            status, data = 500, {"error": "Database operation failed"}

        if status == 204:
            body = b""
        else:
            body = json.dumps(data, ensure_ascii=True).encode("utf-8")
            headers.append(("Content-Type", "application/json"))
        if status != 204:
            headers.append(("Content-Length", str(len(body))))
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def dispatch(self, db, environ):
        path, method = environ["PATH_INFO"], environ["REQUEST_METHOD"]
        if path == "/projects":
            self.allow(method, ("GET", "POST"))
            if method == "GET":
                rows = db.execute("SELECT * FROM projects ORDER BY id")
                return 200, [dict(row) for row in rows], []
            data = read_payload(environ)
            now = timestamp()
            cursor = db.execute(
                """INSERT INTO projects
                   (gitlab_project_id, name, path_with_namespace, web_url,
                    default_branch, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (*[data.get(key) for key in FIELDS], now, now),
            )
            project_id = cursor.lastrowid
            return 201, get_project(db, project_id), [("Location", f"/projects/{project_id}")]

        match = ITEM_PATH.fullmatch(path)
        if match is None or int(match[1]) >= 2**63:
            raise APIError(404, "Route not found")
        project_id = int(match[1])
        if match[2]:
            self.allow(method, ("POST",))
            gitlab_id = get_project(db, project_id)["gitlab_project_id"]
            changes = self.gitlab.project(gitlab_id)
            return 200, update_project(db, project_id, changes, expected_gitlab_id=gitlab_id), []

        self.allow(method, ("GET", "PATCH", "DELETE"))
        if method == "GET":
            return 200, get_project(db, project_id), []
        if method == "PATCH":
            changes = read_payload(environ, partial=True)
            return 200, update_project(db, project_id, changes), []
        if not db.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount:
            raise APIError(404, "Project not found")
        return 204, None, []

    @staticmethod
    def allow(method, allowed):
        if method not in allowed:
            raise APIError(405, "Method not allowed", [("Allow", ", ".join(allowed))])


def create_app():
    return Registry(
        os.environ.get("DATABASE_PATH", "projects.sqlite3"),
        GitLab(os.environ.get("GITLAB_URL", "https://gitlab.com"), os.environ.get("GITLAB_TOKEN")),
    )


if __name__ == "__main__":
    with make_server(
        os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000")), create_app()
    ) as server:
        server.serve_forever()
