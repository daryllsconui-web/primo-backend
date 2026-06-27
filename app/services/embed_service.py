"""
app/services/embed_service.py — sentence-transformers encoding (stub; full impl in task 3)
"""
from __future__ import annotations

from typing import List, Optional

_model = None  # loaded lazily / at startup


def load_model() -> None:
    """Load all-MiniLM-L6-v2 into the module-level singleton."""
    global _model
    from sentence_transformers import SentenceTransformer  # type: ignore

    _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def get_model():
    if _model is None:
        load_model()
    return _model


def encode(texts: List[str]) -> List[List[float]]:
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()
