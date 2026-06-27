"""
app/services/embed_service.py — fastembed encoding (ONNX, CPU-only, low memory)
"""
from __future__ import annotations

from typing import List

_model = None  # loaded lazily at startup


def load_model() -> None:
    global _model
    from fastembed import TextEmbedding  # type: ignore
    _model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")


def get_model():
    if _model is None:
        load_model()
    return _model


def encode(texts: List[str]) -> List[List[float]]:
    model = get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]
