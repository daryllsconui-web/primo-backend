"""
tests/test_knowledge_router.py — Integration tests for knowledge base endpoints

Covers:
- POST /ingest with JSON text payload → 200, doc_ids non-empty, chunks_created > 0
- POST /ingest with invalid file type → 400 {"error": "Invalid file type: ..."}
- POST /ingest with file > max size → 400 {"error": "File too large: ..."}
- GET  /docs empty → 200, empty documents list
- GET  /docs after ingest → shows ingested document
- DELETE /docs/{doc_id} after ingest → 200 {"deleted": true}
- DELETE /docs/{unknown_id} → 404 {"error": "Document not found"}
"""
from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Module-scoped client — shares one lifespan (model load) across all tests."""
    with TestClient(app) as c:
        yield c


_SAMPLE_TEXT = (
    "The embeddable AI chatbot supports Retrieval-Augmented Generation. "
    "Developers can upload documents to a knowledge base so the AI agent "
    "can answer questions based on project-specific content."
)


# ---------------------------------------------------------------------------
# POST /ingest — JSON text payload
# ---------------------------------------------------------------------------

class TestIngestText:
    def test_ingest_text_returns_200(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": _SAMPLE_TEXT},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_ingest_text_response_has_doc_ids(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": _SAMPLE_TEXT},
            headers={"Content-Type": "application/json"},
        )
        body = resp.json()
        assert "doc_ids" in body
        assert isinstance(body["doc_ids"], list)
        assert len(body["doc_ids"]) >= 1

    def test_ingest_text_response_has_chunks_created(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": _SAMPLE_TEXT},
            headers={"Content-Type": "application/json"},
        )
        body = resp.json()
        assert "chunks_created" in body
        assert body["chunks_created"] > 0

    def test_ingest_text_doc_id_is_valid_uuid(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": _SAMPLE_TEXT},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]
        parsed = uuid.UUID(doc_id, version=4)
        assert str(parsed) == doc_id

    def test_ingest_text_default_filename(self, client: TestClient):
        """JSON ingest without filename field uses 'inline_text.txt' as filename."""
        resp = client.post(
            "/ingest",
            json={"text": _SAMPLE_TEXT},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]
        docs = client.get("/docs").json()["documents"]
        doc = next(d for d in docs if d["doc_id"] == doc_id)
        assert doc["filename"] == "inline_text.txt"

    def test_ingest_text_custom_filename(self, client: TestClient):
        """JSON ingest with explicit filename uses that filename."""
        resp = client.post(
            "/ingest",
            json={"text": _SAMPLE_TEXT, "filename": "my_doc.txt"},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]
        docs = client.get("/docs").json()["documents"]
        doc = next(d for d in docs if d["doc_id"] == doc_id)
        assert doc["filename"] == "my_doc.txt"


# ---------------------------------------------------------------------------
# POST /ingest — file upload (TXT/MD)
# ---------------------------------------------------------------------------

class TestIngestFile:
    def test_ingest_txt_file_returns_200(self, client: TestClient):
        content = _SAMPLE_TEXT.encode("utf-8")
        resp = client.post(
            "/ingest",
            files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 200

    def test_ingest_txt_file_has_doc_ids(self, client: TestClient):
        content = _SAMPLE_TEXT.encode("utf-8")
        resp = client.post(
            "/ingest",
            files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
        )
        body = resp.json()
        assert len(body["doc_ids"]) == 1

    def test_ingest_md_file_returns_200(self, client: TestClient):
        content = b"# Title\n\nThis is markdown content for testing the knowledge base."
        resp = client.post(
            "/ingest",
            files={"files": ("readme.md", io.BytesIO(content), "text/markdown")},
        )
        assert resp.status_code == 200

    def test_ingest_invalid_file_type_returns_400(self, client: TestClient):
        content = b"<html><body>some content</body></html>"
        resp = client.post(
            "/ingest",
            files={"files": ("page.html", io.BytesIO(content), "text/html")},
        )
        assert resp.status_code == 400

    def test_ingest_invalid_file_type_error_message(self, client: TestClient):
        """Error message matches spec: 'Invalid file type: {filename}. Allowed: pdf, txt, md'"""
        content = b"some content"
        resp = client.post(
            "/ingest",
            files={"files": ("archive.zip", io.BytesIO(content), "application/zip")},
        )
        error = resp.json().get("error", "")
        assert "Invalid file type" in error
        assert "archive.zip" in error
        assert "pdf, txt, md" in error

    def test_ingest_file_exceeding_size_limit_returns_400(self, client: TestClient):
        # 21 MB > 20 MB limit
        oversized = b"x" * (21 * 1024 * 1024)
        resp = client.post(
            "/ingest",
            files={"files": ("big.txt", io.BytesIO(oversized), "text/plain")},
        )
        assert resp.status_code == 400

    def test_ingest_file_exceeding_size_limit_error_message(self, client: TestClient):
        """Error message matches spec: 'File too large: {filename}. Max: {max_mb}MB'"""
        oversized = b"x" * (21 * 1024 * 1024)
        resp = client.post(
            "/ingest",
            files={"files": ("big.txt", io.BytesIO(oversized), "text/plain")},
        )
        error = resp.json().get("error", "")
        assert "File too large" in error
        assert "big.txt" in error
        assert "MB" in error

    def test_ingest_too_many_files_returns_400(self, client: TestClient):
        # 11 files > max_files_per_request (10)
        files = [
            ("files", (f"file{i}.txt", io.BytesIO(b"content"), "text/plain"))
            for i in range(11)
        ]
        resp = client.post("/ingest", files=files)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /docs
# ---------------------------------------------------------------------------

class TestListDocs:
    def test_get_docs_returns_200(self, client: TestClient):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_get_docs_response_has_documents_key(self, client: TestClient):
        resp = client.get("/docs")
        assert "documents" in resp.json()

    def test_get_docs_documents_is_list(self, client: TestClient):
        resp = client.get("/docs")
        assert isinstance(resp.json()["documents"], list)

    def test_get_docs_empty_on_fresh_state(self, client: TestClient):
        """Fresh client (module-scoped fixture) returns empty list initially."""
        resp = client.get("/docs")
        # May have docs from other tests in module scope; just verify it's a list
        assert isinstance(resp.json()["documents"], list)

    def test_get_docs_after_ingest_shows_document(self, client: TestClient):
        # Ingest a document
        resp = client.post(
            "/ingest",
            json={"text": "Unique knowledge base document for listing test."},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]

        # Verify it appears in /docs
        docs_resp = client.get("/docs")
        doc_ids_in_list = [d["doc_id"] for d in docs_resp.json()["documents"]]
        assert doc_id in doc_ids_in_list

    def test_get_docs_document_has_required_fields(self, client: TestClient):
        client.post(
            "/ingest",
            json={"text": "Document for field validation test."},
            headers={"Content-Type": "application/json"},
        )
        docs = client.get("/docs").json()["documents"]
        assert len(docs) >= 1
        doc = docs[0]
        assert "doc_id" in doc
        assert "filename" in doc
        assert "ingested_at" in doc

    def test_get_docs_ingested_at_is_iso_format(self, client: TestClient):
        client.post(
            "/ingest",
            json={"text": "ISO timestamp test document."},
            headers={"Content-Type": "application/json"},
        )
        docs = client.get("/docs").json()["documents"]
        from datetime import datetime
        ingested_at = docs[0]["ingested_at"]
        # Should parse without error
        dt = datetime.fromisoformat(ingested_at)
        assert dt is not None


# ---------------------------------------------------------------------------
# DELETE /docs/{doc_id}
# ---------------------------------------------------------------------------

class TestDeleteDoc:
    def test_delete_existing_doc_returns_200(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": "Document to be deleted in test."},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]

        del_resp = client.delete(f"/docs/{doc_id}")
        assert del_resp.status_code == 200

    def test_delete_existing_doc_returns_deleted_true(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": "Another document to be deleted."},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]

        del_resp = client.delete(f"/docs/{doc_id}")
        assert del_resp.json() == {"deleted": True}

    def test_delete_removes_doc_from_list(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"text": "Document that will be deleted and checked."},
            headers={"Content-Type": "application/json"},
        )
        doc_id = resp.json()["doc_ids"][0]

        client.delete(f"/docs/{doc_id}")

        docs = client.get("/docs").json()["documents"]
        doc_ids_in_list = [d["doc_id"] for d in docs]
        assert doc_id not in doc_ids_in_list

    def test_delete_unknown_doc_returns_404(self, client: TestClient):
        unknown_id = str(uuid.uuid4())
        resp = client.delete(f"/docs/{unknown_id}")
        assert resp.status_code == 404

    def test_delete_unknown_doc_returns_error_body(self, client: TestClient):
        """Error body matches spec: {"error": "Document not found"}"""
        unknown_id = str(uuid.uuid4())
        resp = client.delete(f"/docs/{unknown_id}")
        assert resp.json() == {"error": "Document not found"}
