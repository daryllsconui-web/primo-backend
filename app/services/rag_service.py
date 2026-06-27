"""
app/services/rag_service.py — RAG pipeline: chunking, embedding, FAISS, retrieval
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore

from app.models.rag_models import Chunk, Document
from app.services.embed_service import encode

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Chunk size in characters (≈ 512 tokens at ~4 chars/token)
_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 50

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=_CHUNK_SIZE,
    chunk_overlap=_CHUNK_OVERLAP,
    length_function=len,
)

# Rebuild FAISS when tombstoned vectors exceed this fraction of total vectors.
_COMPACTION_THRESHOLD = 0.20


def _l2_normalize(vectors: list[list[float]]) -> np.ndarray:
    """L2-normalise a batch of vectors. Returns float32 ndarray."""
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    # Avoid division by zero for zero vectors
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


def ingest(text: str, filename: str, file_type: str, app_state) -> Document:
    """
    Chunk *text*, embed chunks, L2-normalise, add to FAISS, store Document/Chunk records.

    Returns the created Document.
    """
    # 1. Split into chunks
    raw_chunks: list[str] = _splitter.split_text(text)
    if not raw_chunks:
        raw_chunks = [text]

    # 2. Embed and normalise
    embeddings_raw = encode(raw_chunks)
    embeddings = _l2_normalize(embeddings_raw)  # shape (N, 384)

    # 3. Create Document record
    doc_id = str(uuid.uuid4())
    chunk_ids: list[str] = []

    # 4. Store each Chunk and add to FAISS
    for idx, (chunk_text, emb) in enumerate(zip(raw_chunks, embeddings)):
        chunk_id = str(uuid.uuid4())
        chunk_ids.append(chunk_id)

        chunk = Chunk(
            chunk_id=chunk_id,
            doc_id=doc_id,
            text=chunk_text,
            embedding=emb.tolist(),
        )
        app_state.chunk_store[chunk_id] = chunk
        app_state.faiss_id_map.append(chunk_id)

    # Add all vectors to FAISS in one batch
    app_state.faiss_index.add(embeddings)

    # 5. Create and store Document
    doc = Document(
        doc_id=doc_id,
        filename=filename,
        file_type=file_type,  # type: ignore[arg-type]
        ingested_at=datetime.now(timezone.utc),
        chunk_ids=chunk_ids,
    )
    app_state.document_store[doc_id] = doc

    return doc


def retrieve(
    query: str,
    app_state,
    top_k: int = 5,
    threshold: float = 0.70,
) -> list[Chunk]:
    """
    Encode *query*, search FAISS, filter by *threshold*, return qualifying Chunks.

    Tombstoned chunk IDs (soft-deleted) are silently skipped.
    Returns empty list when the index is empty or no chunks meet the threshold.
    """
    if app_state.faiss_index.ntotal == 0:
        return []

    # Encode and normalise query
    query_emb_raw = encode([query])
    query_emb = _l2_normalize(query_emb_raw)  # shape (1, 384)

    k = min(top_k, app_state.faiss_index.ntotal)
    scores, indices = app_state.faiss_index.search(query_emb, k)

    deleted: set[str] = getattr(app_state, "deleted_chunk_ids", set())

    results: list[Chunk] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue  # FAISS returns -1 for padded results
        if float(score) < threshold:
            continue
        chunk_id = app_state.faiss_id_map[int(idx)]
        if chunk_id in deleted:
            continue  # soft-deleted — skip without touching FAISS
        chunk = app_state.chunk_store.get(chunk_id)
        if chunk is not None:
            results.append(chunk)

    return results


def delete_document(doc_id: str, app_state) -> None:
    """
    Soft-delete *doc_id*: remove from document_store and chunk_store,
    then tombstone its chunk IDs so retrieval skips them.

    FAISS is NOT rebuilt on every delete. Instead, chunk IDs are added to
    app_state.deleted_chunk_ids. When tombstones exceed 20% of total vectors,
    compact_index() is triggered automatically to reclaim space.
    """
    doc: Document | None = app_state.document_store.pop(doc_id, None)
    if doc is None:
        raise KeyError(f"Document '{doc_id}' not found.")

    removed_chunk_ids: set[str] = set(doc.chunk_ids)
    for chunk_id in removed_chunk_ids:
        app_state.chunk_store.pop(chunk_id, None)

    # Tombstone — mark as deleted without touching FAISS
    app_state.deleted_chunk_ids.update(removed_chunk_ids)

    logger.info(
        "Document '%s' soft-deleted: %d chunk(s) tombstoned. "
        "Total tombstones: %d / %d FAISS vectors.",
        doc_id,
        len(removed_chunk_ids),
        len(app_state.deleted_chunk_ids),
        app_state.faiss_index.ntotal,
    )

    # Auto-compact when tombstoned fraction exceeds threshold
    total = app_state.faiss_index.ntotal
    if total > 0 and len(app_state.deleted_chunk_ids) / total > _COMPACTION_THRESHOLD:
        logger.info("Tombstone ratio exceeded %.0f%% — triggering auto-compaction.", _COMPACTION_THRESHOLD * 100)
        compact_index(app_state)


def compact_index(app_state) -> None:
    """
    Rebuild the FAISS index keeping only live (non-tombstoned) vectors.

    Uses IndexFlatIP.reconstruct(pos) to read vectors directly from the current
    FAISS index, so this works correctly even when chunk.embedding is empty
    (e.g. after loading from disk where embeddings are not persisted).

    Called automatically by delete_document() when tombstones exceed 20%,
    and explicitly on app shutdown before saving to disk.
    """
    import faiss  # type: ignore

    deleted: set[str] = getattr(app_state, "deleted_chunk_ids", set())
    if not deleted:
        return  # nothing to compact

    EMBEDDING_DIM = 384
    new_index = faiss.IndexFlatIP(EMBEDDING_DIM)
    new_id_map: list[str] = []
    live_vectors: list[np.ndarray] = []

    for pos, chunk_id in enumerate(app_state.faiss_id_map):
        if chunk_id in deleted:
            continue
        if app_state.chunk_store.get(chunk_id) is None:
            continue
        # Read the vector directly from FAISS — works regardless of in-memory embedding state
        vec = app_state.faiss_index.reconstruct(pos)
        live_vectors.append(vec)
        new_id_map.append(chunk_id)

    if live_vectors:
        vectors = np.stack(live_vectors).astype(np.float32)
        new_index.add(vectors)

    app_state.faiss_index = new_index
    app_state.faiss_id_map = new_id_map
    app_state.deleted_chunk_ids.clear()

    logger.info("FAISS compacted — %d live vectors remain.", new_index.ntotal)
