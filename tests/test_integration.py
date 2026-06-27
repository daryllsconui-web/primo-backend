"""
tests/test_integration.py — Integration tests against a live FastAPI process (no mocks except Groq).
Covers: session → chat flow, CORS, ingest → list → delete, GET /health under load.
"""
from __future__ import annotations

import concurrent.futures
import json
import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# Module-scoped client fixture — one lifespan for all integration tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(raw: str) -> list[dict]:
    """Parse raw SSE text into a list of decoded JSON payloads."""
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------------------
# Test 1 — E2E session + chat flow (mocked Groq)
# ---------------------------------------------------------------------------

class TestSessionChatFlow:
    """POST /session/new → POST /chat with mocked stream_completion."""

    def test_e2e_session_chat(self, client: TestClient):
        # Step 1: create a session
        # ContentTypeMiddleware requires Content-Type: application/json for POSTs
        session_resp = client.post(
            "/session/new",
            headers={"Content-Type": "application/json"},
        )
        assert session_resp.status_code == 201
        session_id = session_resp.json()["session_id"]
        assert session_id  # non-empty

        # Step 2: define mock async generator
        async def mock_gen(messages):
            yield 'data: {"token":"Hello"}\n\n'
            yield 'data: {"token":" World"}\n\n'
            yield 'data: {"done":true}\n\n'

        # Step 3: POST /chat with mocked stream_completion
        with patch(
            "app.routers.chat.llm_service.stream_completion",
            new=mock_gen,
        ):
            chat_resp = client.post(
                "/chat",
                json={"session_id": session_id, "message": "Say hello"},
                headers={"Content-Type": "application/json"},
            )

        # Assert HTTP 200
        assert chat_resp.status_code == 200

        # Assert Content-Type is text/event-stream
        content_type = chat_resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        # Parse SSE events
        events = _parse_sse_events(chat_resp.content.decode())

        token_events = [e for e in events if "token" in e]
        done_events = [e for e in events if "done" in e]

        assert len(token_events) >= 1, "Expected at least one token event"
        assert len(done_events) >= 1, "Expected at least one done event"
        assert done_events[0]["done"] is True

    def test_chat_collects_correct_tokens(self, client: TestClient):
        """Verify the concatenated tokens from the mock match expected output."""
        session_resp = client.post(
            "/session/new",
            headers={"Content-Type": "application/json"},
        )
        session_id = session_resp.json()["session_id"]

        async def mock_gen(messages):
            yield 'data: {"token":"Hello"}\n\n'
            yield 'data: {"token":" World"}\n\n'
            yield 'data: {"done":true}\n\n'

        with patch(
            "app.routers.chat.llm_service.stream_completion",
            new=mock_gen,
        ):
            chat_resp = client.post(
                "/chat",
                json={"session_id": session_id, "message": "Say hello"},
                headers={"Content-Type": "application/json"},
            )

        events = _parse_sse_events(chat_resp.content.decode())
        tokens = "".join(e["token"] for e in events if "token" in e)
        assert tokens == "Hello World"


# ---------------------------------------------------------------------------
# Test 2 — CORS: non-allowlisted origin must NOT receive ACAO header
# ---------------------------------------------------------------------------

class TestCORS:
    """CORS origin enforcement.

    The server's CORS_ORIGINS_STR setting determines allowlist behavior:
    - If set to '*', all origins are permitted and ACAO is returned as '*'
    - If set to specific origins, unlisted origins must NOT receive their origin reflected
    Either way, an evil origin must never be explicitly echoed back.
    """

    def test_non_allowlisted_origin_not_reflected(self, client: TestClient):
        """Server must never reflect a non-allowlisted origin explicitly in ACAO header."""
        resp = client.get(
            "/health",
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 200
        acao = resp.headers.get("access-control-allow-origin", "")
        # The specific evil origin must never be echoed back
        assert acao != "https://evil.example.com", (
            "Server must not reflect a non-allowlisted origin in ACAO header"
        )

    def test_cors_does_not_echo_evil_origin(self, client: TestClient):
        """ACAO header value must not be the evil origin (wildcard * or absent is acceptable)."""
        resp = client.get(
            "/health",
            headers={"Origin": "https://evil.example.com"},
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        # Wildcard '*' is acceptable (permissive config); specific evil echo is not
        assert acao in ("", "*"), (
            f"ACAO header '{acao}' should be absent or '*', never the specific evil origin"
        )


# ---------------------------------------------------------------------------
# Test 3 — Ingest → list → delete flow
# ---------------------------------------------------------------------------

class TestIngestListDeleteFlow:
    """Full ingest → list → delete lifecycle."""

    def test_ingest_list_delete_cycle(self, client: TestClient):
        sample_text = (
            "Integration test document: the embeddable AI chatbot supports "
            "Retrieval-Augmented Generation for project-specific content."
        )

        # Step 1: ingest
        ingest_resp = client.post(
            "/ingest",
            json={"text": sample_text},
            headers={"Content-Type": "application/json"},
        )
        assert ingest_resp.status_code == 200
        doc_id = ingest_resp.json()["doc_ids"][0]

        # Step 2: verify doc appears in list
        list_resp = client.get("/docs")
        assert list_resp.status_code == 200
        doc_ids = [d["doc_id"] for d in list_resp.json()["documents"]]
        assert doc_id in doc_ids, f"doc_id {doc_id} not found in /docs after ingest"

        # Step 3: delete
        del_resp = client.delete(f"/docs/{doc_id}")
        assert del_resp.status_code == 200
        assert del_resp.json() == {"deleted": True}

        # Step 4: confirm removal
        list_after = client.get("/docs")
        ids_after = [d["doc_id"] for d in list_after.json()["documents"]]
        assert doc_id not in ids_after, f"doc_id {doc_id} still present after delete"


# ---------------------------------------------------------------------------
# Test 4 — GET /health under 10 concurrent requests
# ---------------------------------------------------------------------------

class TestHealthUnderLoad:
    """Concurrency: 10 simultaneous GET /health requests, each within 500ms."""

    def test_health_10_concurrent_requests(self, client: TestClient):
        results: list[tuple[int, float]] = []

        def hit_health() -> tuple[int, float]:
            t0 = time.time()
            resp = client.get("/health")
            elapsed_ms = (time.time() - t0) * 1000
            return resp.status_code, elapsed_ms

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(hit_health) for _ in range(10)]
            for future in concurrent.futures.as_completed(futures):
                status_code, elapsed_ms = future.result()
                results.append((status_code, elapsed_ms))

        assert len(results) == 10

        for i, (status_code, elapsed_ms) in enumerate(results):
            assert status_code == 200, f"Request {i} returned {status_code}"
            assert elapsed_ms < 500, (
                f"Request {i} took {elapsed_ms:.1f}ms, expected < 500ms"
            )


# ---------------------------------------------------------------------------
# Test 5 — POST /chat with unknown session_id → 404
# ---------------------------------------------------------------------------

class TestChatUnknownSession:
    """Chat endpoint returns 404 for a session_id that doesn't exist."""

    def test_chat_unknown_session_returns_404(self, client: TestClient):
        fake_session_id = str(uuid.uuid4())
        resp = client.post(
            "/chat",
            json={"session_id": fake_session_id, "message": "Hello"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 404

    def test_chat_unknown_session_error_detail(self, client: TestClient):
        """Detail should indicate session_not_found."""
        fake_session_id = str(uuid.uuid4())
        resp = client.post(
            "/chat",
            json={"session_id": fake_session_id, "message": "Hello"},
            headers={"Content-Type": "application/json"},
        )
        body = resp.json()
        detail = body.get("detail", "")
        assert "session_not_found" in str(detail)
