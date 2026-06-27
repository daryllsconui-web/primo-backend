"""
tests/test_health.py — Tests for GET /health endpoint (Requirement 10.1, 10.4)
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_returns_200(client: TestClient):
    """GET /health must return HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_status_is_ok(client: TestClient):
    """Response body must contain status == 'ok'."""
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"


def test_health_uptime_is_non_negative_integer(client: TestClient):
    """Response body must contain uptime as a non-negative integer."""
    response = client.get("/health")
    data = response.json()
    assert "uptime" in data
    assert isinstance(data["uptime"], int)
    assert data["uptime"] >= 0


def test_health_responds_within_500ms(client: TestClient):
    """GET /health must respond within 500ms (Requirement 10.4)."""
    start = time.time()
    response = client.get("/health")
    elapsed_ms = (time.time() - start) * 1000
    assert response.status_code == 200
    assert elapsed_ms < 500, f"Response took {elapsed_ms:.1f}ms, expected < 500ms"
