"""
app/services/persistence_service.py

Saves and loads the FAISS index + document/chunk metadata to disk.
Data is stored in backend/data/ — this folder is gitignored.

Files written:
  data/faiss.index       — FAISS IndexFlatIP binary
  data/faiss_id_map.json — ordered list of chunk_ids matching FAISS positions
  data/document_store.json — dict[doc_id, Document]
  data/chunk_store.json  — dict[chunk_id, Chunk] (without embeddings to save space)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
FAISS_INDEX_PATH = DATA_DIR / "faiss.index"
FAISS_ID_MAP_PATH = DATA_DIR / "faiss_id_map.json"
DOCUMENT_STORE_PATH = DATA_DIR / "document_store.json"
CHUNK_STORE_PATH = DATA_DIR / "chunk_store.json"


def save(app_state) -> None:
    """Persist FAISS index and metadata to disk."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        import faiss  # type: ignore

        # 1. Save FAISS index
        faiss.write_index(app_state.faiss_index, str(FAISS_INDEX_PATH))

        # 2. Save id map
        FAISS_ID_MAP_PATH.write_text(
            json.dumps(app_state.faiss_id_map, ensure_ascii=False), encoding="utf-8"
        )

        # 3. Save document store (Pydantic models → dicts)
        doc_data = {
            doc_id: doc.model_dump(mode="json")
            for doc_id, doc in app_state.document_store.items()
        }
        DOCUMENT_STORE_PATH.write_text(
            json.dumps(doc_data, ensure_ascii=False, default=str), encoding="utf-8"
        )

        # 4. Save chunk store (exclude raw embeddings — they live in FAISS)
        chunk_data = {}
        for chunk_id, chunk in app_state.chunk_store.items():
            d = chunk.model_dump(mode="json")
            d.pop("embedding", None)  # Don't persist embeddings — they're in FAISS
            chunk_data[chunk_id] = d
        CHUNK_STORE_PATH.write_text(
            json.dumps(chunk_data, ensure_ascii=False, default=str), encoding="utf-8"
        )

        logger.info(
            "Knowledge base saved — %d documents, %d chunks, %d FAISS vectors",
            len(app_state.document_store),
            len(app_state.chunk_store),
            app_state.faiss_index.ntotal,
        )

    except Exception as e:
        logger.error("Failed to save knowledge base: %s", e)


def load(app_state) -> bool:
    """
    Load FAISS index and metadata from disk into app_state.
    Returns True if data was loaded, False if no saved data exists.
    """
    if not FAISS_INDEX_PATH.exists():
        logger.info("No saved knowledge base found — starting fresh")
        return False

    try:
        import faiss  # type: ignore
        from app.models.rag_models import Chunk, Document

        # 1. Load FAISS index
        app_state.faiss_index = faiss.read_index(str(FAISS_INDEX_PATH))

        # 2. Load id map
        app_state.faiss_id_map = json.loads(FAISS_ID_MAP_PATH.read_text(encoding="utf-8"))

        # 3. Load document store
        raw_docs = json.loads(DOCUMENT_STORE_PATH.read_text(encoding="utf-8"))
        app_state.document_store = {
            doc_id: Document.model_validate(data)
            for doc_id, data in raw_docs.items()
        }

        # 4. Load chunk store (embeddings are empty — they live in FAISS)
        raw_chunks = json.loads(CHUNK_STORE_PATH.read_text(encoding="utf-8"))
        app_state.chunk_store = {
            chunk_id: Chunk.model_validate({**data, "embedding": []})
            for chunk_id, data in raw_chunks.items()
        }

        logger.info(
            "Knowledge base loaded — %d documents, %d chunks, %d FAISS vectors",
            len(app_state.document_store),
            len(app_state.chunk_store),
            app_state.faiss_index.ntotal,
        )
        return True

    except Exception as e:
        logger.error("Failed to load knowledge base: %s — starting fresh", e)
        return False
