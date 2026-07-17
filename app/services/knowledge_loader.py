"""
app/services/knowledge_loader.py

Auto-ingests all supported files from the backend/knowledge/ folder at startup.

Supported file types:
  - .txt  — plain text
  - .md   — markdown
  - .pdf  — PDF (text extracted via pdfminer.six)
  - .docx — Word documents (text extracted via python-docx)
  - .png / .jpg / .jpeg / .webp — images (text extracted via pytesseract OCR)

Usage (called from app/main.py lifespan):
    from app.services.knowledge_loader import ingest_knowledge_folder
    await ingest_knowledge_folder(app.state, knowledge_dir)
"""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md"}


def _extract_text(file_path: Path) -> str | None:
    """Extract plain text from a file. Returns None if extraction fails."""
    ext = file_path.suffix.lower()

    try:
        if ext in (".txt", ".md"):
            return file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error("Failed to extract text from %s: %s", file_path.name, e)
    return None


def ingest_knowledge_folder(app_state, knowledge_dir: Path | str) -> int:
    """
    Sync knowledge_dir with the RAG index:
      - Remove index entries whose source file no longer exists on disk (stale cleanup)
      - Skip files already indexed (deduplication)
      - Ingest new files not yet in the index
    Returns the number of files newly ingested.
    """
    from app.services.rag_service import ingest, delete_document

    knowledge_dir = Path(knowledge_dir)

    if not knowledge_dir.exists():
        logger.info("Knowledge folder not found: %s — skipping auto-ingest", knowledge_dir)
        return 0

    files = [
        f for f in knowledge_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    current_filenames = {f.name for f in files}

    # Remove stale documents whose source file is no longer on disk
    stale_doc_ids = [
        doc_id for doc_id, doc in list(app_state.document_store.items())
        if doc.filename not in current_filenames
    ]
    for doc_id in stale_doc_ids:
        doc = app_state.document_store.get(doc_id)
        logger.info("  REMOVING stale doc: %s (no longer in knowledge folder)", doc.filename if doc else doc_id)
        try:
            delete_document(doc_id, app_state)
        except Exception as e:
            logger.error("  FAILED to remove stale doc %s: %s", doc_id, e)

    if stale_doc_ids:
        logger.info("Removed %d stale document(s) from index", len(stale_doc_ids))

    if not files:
        logger.info("Knowledge folder is empty — no documents to ingest")
        return 0

    # Build map of filename -> (doc_id, content_hash) for files already in the index
    indexed = {
        doc.filename: (doc_id, getattr(doc, "content_hash", None))
        for doc_id, doc in app_state.document_store.items()
    }

    logger.info("Found %d file(s) in knowledge folder — checking for new or updated files...", len(files))
    ingested = 0

    for file_path in sorted(files):
        text = _extract_text(file_path)
        if not text or not text.strip():
            logger.warning("Skipping %s — no text could be extracted", file_path.name)
            continue

        file_hash = hashlib.md5(text.encode("utf-8")).hexdigest()

        if file_path.name in indexed:
            _, stored_hash = indexed[file_path.name]
            if stored_hash == file_hash:
                logger.info("  SKIP %s — already indexed, content unchanged", file_path.name)
                continue
            else:
                # File changed — remove old version before re-ingesting
                old_doc_id = indexed[file_path.name][0]
                logger.info("  UPDATE %s — content changed, re-ingesting", file_path.name)
                try:
                    delete_document(old_doc_id, app_state)
                except Exception as e:
                    logger.error("  FAILED to remove old version of %s: %s", file_path.name, e)

        ext = file_path.suffix.lower().lstrip(".")
        file_type = ext if ext in ("pdf", "txt", "md") else "txt"

        try:
            doc = ingest(text, file_path.name, file_type, app_state, content_hash=file_hash)
            logger.info(
                "  OK %s - %d chunk(s) (doc_id: %s)",
                file_path.name, len(doc.chunk_ids), doc.doc_id
            )
            ingested += 1
        except Exception as e:
            logger.error("  FAILED to ingest %s: %s", file_path.name, e)

    logger.info("Knowledge base ready — %d file(s) ingested/updated, %d total documents", ingested, len(app_state.document_store))
    return ingested
