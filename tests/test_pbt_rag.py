# Feature: embeddable-ai-chatbot, Property 4: RAG similarity threshold gate
# Validates: Requirements 6.3, 6.4

from hypothesis import given, settings
from hypothesis import strategies as st
from types import SimpleNamespace
from app.services.session_service import create_session, build_prompt
from app.models.session import Session

# Strategy: generate a list of chunk dicts (may be empty or non-empty)
chunk_dict_st = st.fixed_dictionaries({
    "filename": st.text(min_size=1, max_size=20),
    "chunk_index": st.integers(min_value=0, max_value=100),
    "text": st.text(min_size=1, max_size=200),
})

cfg = SimpleNamespace(agent_name="Bot", agent_personality=None, agent_tone=None, agent_system_prompt=None)

@given(st.lists(chunk_dict_st, min_size=0, max_size=5))
@settings(max_examples=100)
def test_no_chunks_means_no_context_block(chunks_list):
    """When no chunks are passed (simulate all scores below threshold), prompt has no [CONTEXT] block."""
    store = {}
    session = create_session(store)
    prompt = build_prompt(session, "test query", [], cfg)
    # The last message is the user message — should be plain text, no [CONTEXT]
    last_msg = prompt[-1]
    assert "[CONTEXT]" not in last_msg.content
    assert "[/CONTEXT]" not in last_msg.content

@given(st.lists(chunk_dict_st, min_size=1, max_size=5))
@settings(max_examples=100)
def test_chunks_present_means_context_block_injected(chunks_list):
    """When chunks are passed (simulate scores >= threshold), prompt has [CONTEXT] block."""
    store = {}
    session = create_session(store)
    prompt = build_prompt(session, "test query", chunks_list, cfg)
    last_msg = prompt[-1]
    assert "[CONTEXT]" in last_msg.content
    assert "[/CONTEXT]" in last_msg.content

@given(st.lists(chunk_dict_st, min_size=1, max_size=5))
@settings(max_examples=100)
def test_only_qualifying_chunks_in_context_block(chunks_list):
    """All passed chunks appear in the [CONTEXT] block."""
    store = {}
    session = create_session(store)
    prompt = build_prompt(session, "test query", chunks_list, cfg)
    last_msg = prompt[-1]
    for chunk in chunks_list:
        assert chunk["text"] in last_msg.content


# Feature: embeddable-ai-chatbot, Property 5: Knowledge base round-trip — ingest then retrieve
# Validates: Requirements 6.2, 6.3

import faiss
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from app.services.rag_service import ingest, retrieve
from types import SimpleNamespace


@given(
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
        min_size=50,
        max_size=500,
    )
)
@settings(max_examples=100, deadline=None)
def test_ingest_then_retrieve_finds_chunk(text):
    """After ingesting a document, querying with the same text retrieves >= 1 chunk with score >= 0.70."""
    # Fresh in-memory app_state per run
    app_state = SimpleNamespace(
        faiss_index=faiss.IndexFlatIP(384),
        faiss_id_map=[],
        document_store={},
        chunk_store={},
    )

    # Ingest the text
    doc = ingest(text, "test.txt", "txt", app_state)
    assert len(doc.chunk_ids) >= 1

    # Retrieve using the same text as query
    results = retrieve(text[:200], app_state, top_k=5, threshold=0.70)
    assert len(results) >= 1, (
        f"Expected at least 1 chunk with score >= 0.70, got 0 for text: {text[:50]!r}"
    )
