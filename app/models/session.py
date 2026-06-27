"""
app/models/session.py — Session and Message Pydantic models
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Session(BaseModel):
    session_id: str  # UUID v4
    messages: List[Message] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Updated on every user interaction — used by TTL cleanup
    last_active_at: datetime = Field(default_factory=datetime.utcnow)
