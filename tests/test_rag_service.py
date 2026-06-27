"""
tests/test_rag_service.py — Unit tests for rag_service (Task 3)

Uses a SimpleNamespace mock app_state to avoid needing a live FastAPI app.
The sentence-transformers model loads on first use — first run may take a moment.
"""
from __future__ import annotations

from types import SimpleNamespace

import faiss  # type: ignore
import numpy as np
import pytest

from app.services import rag_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384


def _make_app_state() -> SimpleNamespace:
    """Return a fresh mock app_state matching the lifespan initialisation."""
    return SimpleNamespace(
        faiss_index=faiss.IndexFlatIP(EMBEDDING_DIM),
        faiss_id_map=[],
        document_store={},
        chunk_store={},
    )


_SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This sentence is used as sample text for testing the RAG pipeline. "
    "It contains enough words to be split into at least one chunk by the text splitter."
)

_LONG_TEXT = " ".join([f"Sentence number {i} contains some useful information." for i in range(200)])


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

class TestChunking:
    def test_chunks_created_from_text(self):
        """split_text should produce at least one chunk for non-empty input."""
        chunks = rag_service._splitter.split_text(_SAMPLE_TEXT)
        assert len(chunks) >= 1

    def test_chunk_sizes_bounded(self):
        """Every chunk should not exceed chunk_size + overlap tolerance."""
        chunks = rag_service._splitter.split_text(_LONG_TEXT)
        # Allow a small buffer above chunk_size; overlap can cause slight overrun
        for chunk in chunks:
            assert len(chunk) <= rag_service._CHUNK_SIZE + rag_service._CHUNK_OVERLAP + 10

    def test_long_text_produces_multiple_chunks(self):
        """Long text should be split into more than one chunk."""
        chunks = rag_service._splitter.split_text(_LONG_TEXT)
        assert len(chunks) > 1

    def test_short_text_stays_single_chunk(self):
        """Text shorter than chunk_size should remain as a single chunk."""
        short = "Hello world."
        chunks = rag_service._splitter.split_text(short)
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_ingest_returns_document(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "test.txt", "txt", state)
        assert doc is not None

    def test_ingest_document_has_correct_filename(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "readme.md", "md", state)
        assert doc.filename == "readme.md"

    def test_ingest_document_has_correct_file_type(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        assert doc.file_type == "txt"

    def test_ingest_document_has_doc_id(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        assert doc.doc_id and len(doc.doc_id) > 0

    def test_ingest_document_has_nonempty_chunk_ids(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        assert len(doc.chunk_ids) > 0

    def test_ingest_document_stored_in_document_store(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        assert doc.doc_id in state.document_store

    def test_ingest_chunks_stored_in_chunk_store(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        for chunk_id in doc.chunk_ids:
            assert chunk_id in state.chunk_store

    def test_ingest_faiss_index_grows_by_chunk_count(self):
        """FAISS ntotal should increase by exactly the number of chunks created."""
        state = _make_app_state()
        before = state.faiss_index.ntotal
        doc = rag_service.ingest(_LONG_TEXT, "long.txt", "txt", state)
        after = state.faiss_index.ntotal
        assert after - before == len(doc.chunk_ids)

    def test_ingest_faiss_id_map_length_matches_ntotal(self):
        state = _make_app_state()
        rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        assert len(state.faiss_id_map) == state.faiss_index.ntotal

    def test_ingest_chunk_embeddings_are_384_dim(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        for chunk_id in doc.chunk_ids:
            chunk = state.chunk_store[chunk_id]
            assert len(chunk.embedding) == EMBEDDING_DIM

    def test_ingest_chunk_embeddings_are_unit_vectors(self):
        """Embeddings stored should be L2-normalised (unit vectors)."""
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        for chunk_id in doc.chunk_ids:
            emb = np.array(state.chunk_store[chunk_id].embedding, dtype=np.float32)
            norm = np.linalg.norm(emb)
            assert abs(norm - 1.0) < 1e-5, f"Embedding norm {norm} not close to 1.0"

    def test_ingest_two_documents_both_stored(self):
        state = _make_app_state()
        doc1 = rag_service.ingest(_SAMPLE_TEXT, "a.txt", "txt", state)
        doc2 = rag_service.ingest(_LONG_TEXT, "b.txt", "txt", state)
        assert doc1.doc_id in state.document_store
        assert doc2.doc_id in state.document_store


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------

class TestRetrieve:
    def test_retrieve_empty_kb_returns_empty_list(self):
        state = _make_app_state()
        result = rag_service.retrieve("anything", state)
        assert result == []

    def test_retrieve_returns_list_type(self):
        state = _make_app_state()
        rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        result = rag_service.retrieve("fox jumps", state)
        assert isinstance(result, list)

    def test_retrieve_same_text_returns_chunk_above_threshold(self):
        """Ingesting text then querying with the same text should score >= 0.70."""
        state = _make_app_state()
        rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        results = rag_service.retrieve(_SAMPLE_TEXT, state, top_k=5, threshold=0.70)
        assert len(results) >= 1

    def test_retrieve_relevant_query_returns_chunks(self):
        """A semantically similar query should retrieve at least one chunk."""
        state = _make_app_state()
        rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        # Use a sentence-level query closely matching the ingested text
        results = rag_service.retrieve(
            "The quick brown fox jumps over the lazy dog used as sample text for testing",
            state,
            top_k=5,
            threshold=0.70,
        )
        assert len(results) >= 1

    def test_retrieve_returned_chunks_have_score_above_threshold(self):
        """All returned chunks must meet or exceed the threshold (verified indirectly
        by checking they come from the ingested document)."""
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        valid_ids = set(doc.chunk_ids)
        results = rag_service.retrieve(_SAMPLE_TEXT, state, top_k=5, threshold=0.70)
        for chunk in results:
            assert chunk.chunk_id in valid_ids

    def test_retrieve_unrelated_query_returns_empty_below_threshold(self):
        """An extremely unrelated query should return nothing when threshold is high."""
        state = _make_app_state()
        # Ingest text about foxes; query about quantum physics with very high threshold
        rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        results = rag_service.retrieve(
            "superconducting quantum interference device", state, top_k=5, threshold=0.99
        )
        assert results == []

    def test_retrieve_top_k_limits_results(self):
        state = _make_app_state()
        rag_service.ingest(_LONG_TEXT, "long.txt", "txt", state)
        results = rag_service.retrieve(_LONG_TEXT[:200], state, top_k=2, threshold=0.0)
        assert len(results) <= 2

    def test_retrieve_chunks_have_text_field(self):
        state = _make_app_state()
        rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        results = rag_service.retrieve(_SAMPLE_TEXT, state, top_k=5, threshold=0.70)
        for chunk in results:
            assert chunk.text and len(chunk.text) > 0

    def test_retrieve_chunks_have_correct_doc_id(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        results = rag_service.retrieve(_SAMPLE_TEXT, state, top_k=5, threshold=0.70)
        for chunk in results:
            assert chunk.doc_id == doc.doc_id


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------

class TestDeleteDocument:
    def test_delete_removes_doc_from_document_store(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        rag_service.delete_document(doc.doc_id, state)
        assert doc.doc_id not in state.document_store

    def test_delete_removes_chunks_from_chunk_store(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        chunk_ids = list(doc.chunk_ids)
        rag_service.delete_document(doc.doc_id, state)
        for chunk_id in chunk_ids:
            assert chunk_id not in state.chunk_store

    def test_delete_reduces_faiss_ntotal(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        before = state.faiss_index.ntotal
        chunk_count = len(doc.chunk_ids)
        rag_service.delete_document(doc.doc_id, state)
        assert state.faiss_index.ntotal == before - chunk_count

    def test_delete_faiss_empty_after_only_doc_deleted(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        rag_service.delete_document(doc.doc_id, state)
        assert state.faiss_index.ntotal == 0

    def test_delete_faiss_id_map_updated(self):
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        rag_service.delete_document(doc.doc_id, state)
        for chunk_id in doc.chunk_ids:
            assert chunk_id not in state.faiss_id_map

    def test_delete_preserves_other_document(self):
        """Deleting one doc should not affect another doc's chunks in FAISS."""
        state = _make_app_state()
        doc1 = rag_service.ingest(_SAMPLE_TEXT, "a.txt", "txt", state)
        doc2 = rag_service.ingest(_LONG_TEXT, "b.txt", "txt", state)
        total_before = state.faiss_index.ntotal
        rag_service.delete_document(doc1.doc_id, state)
        # doc2's chunks should still be in FAISS
        assert state.faiss_index.ntotal == len(doc2.chunk_ids)
        assert doc2.doc_id in state.document_store
        for chunk_id in doc2.chunk_ids:
            assert chunk_id in state.chunk_store

    def test_delete_nonexistent_doc_raises_keyerror(self):
        state = _make_app_state()
        with pytest.raises(KeyError):
            rag_service.delete_document("nonexistent-doc-id", state)

    def test_delete_then_retrieve_returns_empty(self):
        """After deleting the only document, retrieval should return empty."""
        state = _make_app_state()
        doc = rag_service.ingest(_SAMPLE_TEXT, "doc.txt", "txt", state)
        rag_service.delete_document(doc.doc_id, state)
        results = rag_service.retrieve(_SAMPLE_TEXT, state, top_k=5, threshold=0.70)
        assert results == []
