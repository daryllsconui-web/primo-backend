"""
app/models/rag_models.py — Document and Chunk Pydantic models for RAG pipeline
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel


class Document(BaseModel):
    doc_id: str  # UUID v4
    filename: str
    file_type: Literal["pdf", "txt", "md"]
    ingested_at: datetime
    chunk_ids: List[str]  # references into vector store


class Chunk(BaseModel):
    chunk_id: str  # UUID v4
    doc_id: str
    text: str
    embedding: List[float]  # 384-dim for all-MiniLM-L6-v2
