"""
tests/test_session_router.py — Integration tests for session endpoints
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /session/new
# ---------------------------------------------------------------------------

JSON_HEADERS = {"Content-Type": "application/json"}


def test_post_session_new_returns_201(client: TestClient):
    resp = client.post("/session/new", headers=JSON_HEADERS)
    assert resp.status_code == 201


def test_post_session_new_returns_session_id(client: TestClient):
    resp = client.post("/session/new", headers=JSON_HEADERS)
    body = resp.json()
    assert "session_id" in body


def test_post_session_new_session_id_is_uuid_v4(client: TestClient):
    resp = client.post("/session/new", headers=JSON_HEADERS)
    sid = resp.json()["session_id"]
    parsed = uuid.UUID(sid, version=4)
    assert str(parsed) == sid


def test_post_session_new_two_calls_return_different_ids(client: TestClient):
    r1 = client.post("/session/new", headers=JSON_HEADERS)
    r2 = client.post("/session/new", headers=JSON_HEADERS)
    assert r1.json()["session_id"] != r2.json()["session_id"]


# ---------------------------------------------------------------------------
# GET /session/{session_id}
# ---------------------------------------------------------------------------

def test_get_session_returns_200_for_existing(client: TestClient):
    sid = client.post("/session/new", headers=JSON_HEADERS).json()["session_id"]
    resp = client.get(f"/session/{sid}")
    assert resp.status_code == 200


def test_get_session_body_contains_session_id(client: TestClient):
    sid = client.post("/session/new", headers=JSON_HEADERS).json()["session_id"]
    body = client.get(f"/session/{sid}").json()
    assert body["session_id"] == sid


def test_get_session_returns_empty_messages_on_new_session(client: TestClient):
    sid = client.post("/session/new", headers=JSON_HEADERS).json()["session_id"]
    body = client.get(f"/session/{sid}").json()
    assert body["messages"] == []


def test_get_session_returns_404_for_unknown(client: TestClient):
    resp = client.get(f"/session/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_session_404_body_contains_error(client: TestClient):
    resp = client.get(f"/session/{uuid.uuid4()}")
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "session_not_found"
