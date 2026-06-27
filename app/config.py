"""
app/config.py — Pydantic Settings loaded from .env
"""
from __future__ import annotations

import json
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.default_prompt import DEFAULT_SYSTEM_PROMPT

ALLOWED_MODELS: frozenset[str] = frozenset(
    {
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama-3.1-70b-versatile",
        "gemma2-9b-it",
        "llama3-groq-70b-8192-tool-use-preview",
        # Legacy — kept for backward compat but decommissioned by Groq
        "llama3-8b-8192",
        "llama3-70b-8192",
        "mixtral-8x7b-32768",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Required ---
    groq_api_key: str

    # --- Optional: logging ---
    log_level: str = "INFO"

    # --- Optional: agent behaviour ---
    agent_name: str = "Primo"
    groq_model: str = "llama-3.3-70b-versatile"
    agent_personality: Optional[str] = "professional, warm, consultative, strategic, caring"
    agent_tone: Optional[str] = "calm, clear, and human"
    agent_system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT

    # --- Optional: CORS ---
    # Comma-separated or JSON array of allowed origins. Use * for all (dev only).
    cors_origins_str: str = "*"

    # --- Optional: admin key for knowledge base management ---
    # Set ADMIN_API_KEY in .env to protect POST /ingest, GET /docs, DELETE /docs/{id}
    # Leave unset (empty) to disable protection — dev mode only
    admin_api_key: Optional[str] = None

    # --- Optional: Session TTL ---
    # Sessions inactive longer than this are deleted by the background cleanup task.
    session_ttl_minutes: int = 30
    # How often (in minutes) the cleanup task runs.
    session_cleanup_interval_minutes: int = 10

    # --- Optional: Input limits ---
    # Maximum characters allowed in a single chat message (default: 2000 ≈ 400 words)
    max_message_chars: int = 2000
    # Maximum characters allowed in the inline JSON text payload for /ingest
    max_inline_text_chars: int = 50000

    # --- Optional: RAG ---
    similarity_threshold: float = 0.70
    top_k: int = 5
    max_file_size_mb: int = 20
    max_files_per_request: int = 10

    @property
    def cors_origins(self) -> List[str]:
        """Parse comma-separated or JSON-array CORS_ORIGINS into a list."""
        v = self.cors_origins_str.strip()
        if v.startswith("["):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
        return [o.strip() for o in v.split(",") if o.strip()]

    # --- Validators ---

    @field_validator("groq_model")
    @classmethod
    def model_must_be_allowed(cls, v: str) -> str:
        if v not in ALLOWED_MODELS:
            raise ValueError(
                f"GROQ_MODEL '{v}' is not supported. "
                f"Allowed values: {sorted(ALLOWED_MODELS)}"
            )
        return v


# Singleton — imported everywhere in the app
settings = Settings()
