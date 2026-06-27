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

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}


def _extract_text(file_path: Path) -> str | None:
    """Extract plain text from a file. Returns None if extraction fails."""
    ext = file_path.suffix.lower()

    try:
        if ext in (".txt", ".md"):
            return file_path.read_text(encoding="utf-8", errors="ignore")

        elif ext == ".pdf":
            from pdfminer.high_level import extract_text  # type: ignore
            return extract_text(str(file_path))

        elif ext == ".docx":
            from docx import Document  # type: ignore
            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

        elif ext in (".png", ".jpg", ".jpeg", ".webp"):
            try:
                import sys
                import pytesseract  # type: ignore
                from PIL import Image  # type: ignore
                if sys.platform == "win32":
                    pytesseract.pytesseract.tesseract_cmd = (
                        r"C:\Users\JanDaryllCon-Ui\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
                    )
                img = Image.open(str(file_path))
                text = pytesseract.image_to_string(img)
                return text if text.strip() else None
            except Exception as e:
                logger.warning(
                    "Image OCR skipped for %s: %s",
                    file_path.name, e
                )
                return None

    except Exception as e:
        logger.error("Failed to extract text from %s: %s", file_path.name, e)
        return None


def ingest_knowledge_folder(app_state, knowledge_dir: Path | str) -> int:
    """
    Scan knowledge_dir and ingest all supported files into the RAG pipeline.
    Returns the number of files successfully ingested.
    """
    from app.services.rag_service import ingest

    knowledge_dir = Path(knowledge_dir)

    if not knowledge_dir.exists():
        logger.info("Knowledge folder not found: %s — skipping auto-ingest", knowledge_dir)
        return 0

    files = [
        f for f in knowledge_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        logger.info("Knowledge folder is empty — no documents to ingest")
        return 0

    logger.info("Found %d file(s) in knowledge folder — ingesting...", len(files))
    ingested = 0

    for file_path in sorted(files):
        text = _extract_text(file_path)
        if not text or not text.strip():
            logger.warning("Skipping %s — no text could be extracted", file_path.name)
            continue

        ext = file_path.suffix.lower().lstrip(".")
        # Normalise file_type to one of the allowed Literal values
        file_type = ext if ext in ("pdf", "txt", "md") else "txt"

        try:
            doc = ingest(text, file_path.name, file_type, app_state)
            logger.info(
                "  OK %s - %d chunk(s) (doc_id: %s)",
                file_path.name, len(doc.chunk_ids), doc.doc_id
            )
            ingested += 1
        except Exception as e:
            logger.error("  FAILED to ingest %s: %s", file_path.name, e)

    logger.info("Knowledge base ready — %d/%d file(s) ingested", ingested, len(files))
    return ingested
