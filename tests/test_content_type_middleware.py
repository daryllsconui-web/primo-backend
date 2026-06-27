"""
tests/test_content_type_middleware.py — ContentTypeMiddleware unit tests
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

JSON_CT = {"Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST without Content-Type → 400
# ---------------------------------------------------------------------------

def test_post_without_content_type_returns_400(client: TestClient):
    """POST /session/new with no Content-Type header must be rejected."""
    resp = client.post("/session/new", headers={})
    assert resp.status_code == 400


def test_post_without_content_type_error_body(client: TestClient):
    resp = client.post("/session/new", headers={})
    assert resp.json() == {"error": "Expected Content-Type: application/json"}


# ---------------------------------------------------------------------------
# POST with wrong Content-Type → 400
# ---------------------------------------------------------------------------

def test_post_with_form_content_type_returns_400(client: TestClient):
    resp = client.post(
        "/session/new",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400


def test_post_with_text_content_type_returns_400(client: TestClient):
    resp = client.post(
        "/session/new",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 400


def test_post_wrong_content_type_error_body(client: TestClient):
    resp = client.post(
        "/session/new",
        headers={"Content-Type": "text/xml"},
    )
    assert resp.json() == {"error": "Expected Content-Type: application/json"}


# ---------------------------------------------------------------------------
# POST with application/json → passes through (not 400)
# ---------------------------------------------------------------------------

def test_post_with_application_json_passes_through(client: TestClient):
    """POST /session/new with application/json must not be blocked by middleware."""
    resp = client.post("/session/new", headers=JSON_CT)
    assert resp.status_code != 400


def test_post_with_json_charset_passes_through(client: TestClient):
    """application/json; charset=utf-8 must also be accepted."""
    resp = client.post(
        "/session/new",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert resp.status_code != 400


# ---------------------------------------------------------------------------
# GET request → not blocked
# ---------------------------------------------------------------------------

def test_get_request_not_blocked(client: TestClient):
    """GET /health should pass through regardless of Content-Type."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_get_session_not_blocked_by_middleware(client: TestClient):
    """GET /session/{id} with no Content-Type should not be blocked."""
    import uuid
    resp = client.get(f"/session/{uuid.uuid4()}")
    # 404 expected (unknown session), but NOT a 400 from middleware
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /ingest → not blocked (exempt path)
# ---------------------------------------------------------------------------

def test_post_ingest_with_multipart_not_blocked(client: TestClient):
    """POST /ingest with multipart/form-data must NOT be rejected by ContentTypeMiddleware."""
    resp = client.post(
        "/ingest",
        headers={"Content-Type": "multipart/form-data; boundary=----boundary"},
        content=b"",
    )
    # Middleware should not return 400 — any other status code is acceptable here
    assert resp.status_code != 400


def test_post_ingest_without_content_type_not_blocked(client: TestClient):
    """POST /ingest with no Content-Type must NOT return 400 from ContentTypeMiddleware."""
    resp = client.post("/ingest", headers={})
    assert resp.status_code != 400
