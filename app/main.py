"""
app/main.py — FastAPI application factory with lifespan
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import faiss  # type: ignore
import numpy as np
from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.logging_config import configure_secrets, setup_logging
from app.middleware.content_type import ContentTypeMiddleware
from app.middleware.cors import add_cors_middleware
from app.middleware.exception_handler import unhandled_exception_handler
from app.middleware.logging import RequestLoggingMiddleware
from app.routers import chat, health, knowledge, session

# Configure structured JSON logging before anything else logs
setup_logging(level=settings.log_level)
configure_secrets([settings.groq_api_key, settings.admin_api_key])
logger = logging.getLogger(__name__)

# Rate limiter — keyed by client IP
limiter = Limiter(key_func=get_remote_address)


async def _session_cleanup_loop(app: FastAPI) -> None:
    """Background task: periodically remove expired sessions."""
    from app.services.session_service import cleanup_expired_sessions

    interval_seconds = settings.session_cleanup_interval_minutes * 60
    ttl_minutes = settings.session_ttl_minutes

    logger.info(
        "Session cleanup task started — TTL: %d min, interval: %d min.",
        ttl_minutes,
        settings.session_cleanup_interval_minutes,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            removed = cleanup_expired_sessions(app.state.session_store, ttl_minutes)
            if removed:
                logger.info("Active sessions after cleanup: %d", len(app.state.session_store))
        except Exception:
            logger.exception("Error during session cleanup — will retry next interval.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: initialise shared state. Shutdown: clean up."""
    # --- Startup ---
    app.state.start_time = time.time()

    # In-memory session store: dict[session_id, Session]
    app.state.session_store: dict = {}

    # In-memory document registry: dict[doc_id, Document]
    app.state.document_store: dict = {}

    # Chunk registry: dict[chunk_id, Chunk]
    app.state.chunk_store: dict = {}

    # FAISS index — 384-dim (all-MiniLM-L6-v2), inner product with L2-normalised vectors
    EMBEDDING_DIM = 384
    app.state.faiss_index = faiss.IndexFlatIP(EMBEDDING_DIM)

    # Ordered list of chunk_ids matching FAISS index positions
    app.state.faiss_id_map: list[str] = []

    # Soft-deleted chunk IDs: skipped during retrieval, cleared on compaction
    app.state.deleted_chunk_ids: set[str] = set()

    logger.info("Loading embedding model: sentence-transformers/all-MiniLM-L6-v2")
    from app.services import embed_service
    embed_service.load_model()
    logger.info("Embedding model loaded.")

    logger.info(
        "Backend started.",
        extra={"agent_name": settings.agent_name, "groq_model": settings.groq_model},
    )

    # Load persisted knowledge base from disk (if available)
    from app.services.persistence_service import load as load_kb, save as save_kb
    loaded = load_kb(app.state)

    if not loaded:
        # No saved data — auto-ingest knowledge/ folder
        from pathlib import Path
        from app.services.knowledge_loader import ingest_knowledge_folder
        knowledge_dir = Path(__file__).parent.parent / "knowledge"
        ingest_knowledge_folder(app.state, knowledge_dir)
    else:
        # Data loaded — still check knowledge/ for any NEW files not yet ingested
        from pathlib import Path
        from app.services.knowledge_loader import ingest_knowledge_folder
        knowledge_dir = Path(__file__).parent.parent / "knowledge"
        ingest_knowledge_folder(app.state, knowledge_dir)

    # Start background session cleanup task
    cleanup_task = asyncio.create_task(_session_cleanup_loop(app))

    yield  # --- application running ---

    # --- Shutdown: cancel cleanup task, compact FAISS, save knowledge base to disk ---
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Compact before saving so persisted state never contains tombstoned vectors
    from app.services.rag_service import compact_index
    compact_index(app.state)

    save_kb(app.state)
    logger.info("Backend shut down cleanly.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Embeddable AI Chatbot",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api-docs",
        redoc_url="/api-redoc",
    )

    # --- Rate limiter state ---
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # --- Middleware (outermost first) ---
    add_cors_middleware(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(ContentTypeMiddleware)

    # --- Exception handlers ---
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # --- Routers ---
    app.include_router(health.router)
    app.include_router(session.router)
    app.include_router(chat.router)
    app.include_router(knowledge.router)

    return app


app = create_app()
