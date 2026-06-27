"""
app/routers/knowledge.py — Knowledge base endpoints

POST /ingest  — ingest files (PDF/TXT/MD) or plain text
GET  /docs    — list all ingested documents
DELETE /docs/{doc_id} — delete a document and its embeddings
"""
from __future__ import annotations

import io
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.services import rag_service

router = APIRouter(tags=["knowledge"])


def _require_admin(request: Request) -> None:
    """Raise HTTP 401 if ADMIN_API_KEY is set and the request doesn't include it."""
    if not settings.admin_api_key:
        return  # No key configured — open access (dev mode)
    provided = request.headers.get("X-Admin-Key", "")
    if provided != settings.admin_api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid or missing X-Admin-Key header"},
        )

# ---------------------------------------------------------------------------
# Allowed file extensions
# ---------------------------------------------------------------------------
_ALLOWED_EXTENSIONS = {"pdf", "txt", "md"}


def _extension(filename: str) -> str:
    """Return lowercased file extension without leading dot."""
    parts = filename.rsplit(".", 1)
    return parts[-1].lower() if len(parts) == 2 else ""


def _extract_text_from_file(content: bytes, filename: str) -> str:
    """Extract plain text from uploaded file bytes."""
    from pdfminer.high_level import extract_text  # type: ignore

    ext = _extension(filename)
    if ext == "pdf":
        return extract_text(io.BytesIO(content))
    # txt / md
    return content.decode("utf-8")


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------
@router.post("/ingest")
async def ingest(request: Request):
    """
    Accept either:
    - multipart/form-data  with files[]
    - application/json     with {"text": "...", "filename": "..."} (filename optional)
    """
    _require_admin(request)
    content_type = request.headers.get("content-type", "")
    app_state = request.app.state

    # ------------------------------------------------------------------
    # Branch 1: JSON text payload
    # ------------------------------------------------------------------
    if "application/json" in content_type:
        body = await request.json()
        text = body.get("text", "")
        filename = body.get("filename", "inline_text.txt")

        if not text or not text.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "Missing or empty 'text' field in JSON body."},
            )

        if len(text) > settings.max_inline_text_chars:
            return JSONResponse(
                status_code=400,
                content={
                    "error": (
                        f"'text' field too long: {len(text)} characters received, "
                        f"maximum allowed is {settings.max_inline_text_chars}."
                    )
                },
            )

        if len(filename) > 255:
            return JSONResponse(
                status_code=400,
                content={"error": "filename exceeds the 255-character limit."},
            )

        doc = rag_service.ingest(text.strip(), filename, "txt", app_state)
        return JSONResponse(
            status_code=200,
            content={"doc_ids": [doc.doc_id], "chunks_created": len(doc.chunk_ids)},
        )

    # ------------------------------------------------------------------
    # Branch 2: multipart/form-data file upload
    # ------------------------------------------------------------------
    if "multipart/form-data" in content_type:
        form = await request.form()
        files: List[UploadFile] = form.getlist("files")  # type: ignore[assignment]

        # Also support single "file" key
        if not files:
            single = form.get("files")
            if single is not None:
                files = [single]  # type: ignore[list-item]

        if not files:
            return JSONResponse(
                status_code=400,
                content={"error": "No files provided."},
            )

        # File count limit
        max_files = settings.max_files_per_request
        if len(files) > max_files:
            return JSONResponse(
                status_code=400,
                content={"error": f"Too many files. Maximum allowed is {max_files} per request."},
            )

        max_bytes = settings.max_file_size_mb * 1024 * 1024
        max_mb = settings.max_file_size_mb
        doc_ids: list[str] = []
        total_chunks = 0

        for upload in files:
            filename = upload.filename or "upload"
            ext = _extension(filename)

            # Validate extension
            if ext not in _ALLOWED_EXTENSIONS:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Invalid file type: {filename}. Allowed: pdf, txt, md"},
                )

            content = await upload.read()

            # Validate size
            if len(content) > max_bytes:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"File too large: {filename}. Max: {max_mb}MB"},
                )

            text = _extract_text_from_file(content, filename)
            file_type = ext  # "pdf" | "txt" | "md"
            doc = rag_service.ingest(text, filename, file_type, app_state)  # type: ignore[arg-type]
            doc_ids.append(doc.doc_id)
            total_chunks += len(doc.chunk_ids)

        return JSONResponse(
            status_code=200,
            content={"doc_ids": doc_ids, "chunks_created": total_chunks},
        )

    return JSONResponse(
        status_code=400,
        content={"error": "Unsupported Content-Type. Use multipart/form-data or application/json."},
    )


# ---------------------------------------------------------------------------
# GET /docs
# ---------------------------------------------------------------------------
@router.get("/docs")
async def list_docs(request: Request):
    """Return all ingested documents (doc_id, filename, ingested_at)."""
    _require_admin(request)
    document_store = request.app.state.document_store
    documents = [
        {
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "ingested_at": doc.ingested_at.isoformat(),
        }
        for doc in document_store.values()
    ]
    return JSONResponse(status_code=200, content={"documents": documents})


# ---------------------------------------------------------------------------
# DELETE /docs/{doc_id}
# ---------------------------------------------------------------------------
@router.delete("/docs/{doc_id}")
async def delete_doc(doc_id: str, request: Request):
    """Delete a document and all its associated embeddings."""
    _require_admin(request)
    try:
        rag_service.delete_document(doc_id, request.app.state)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"error": "Document not found"},
        )
    return JSONResponse(status_code=200, content={"deleted": True})
