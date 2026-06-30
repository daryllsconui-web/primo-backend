"""
app/routers/chat.py — POST /chat SSE streaming endpoint
"""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.models.session import Message, Session
from app.services import llm_service, rag_service, session_service

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list[dict] = []  # frontend owns conversation history (stateless design)

    @field_validator("session_id")
    @classmethod
    def session_id_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("session_id must not be empty.")
        return v

    @field_validator("message")
    @classmethod
    def message_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty.")
        if len(v) > settings.max_message_chars:
            raise ValueError(
                f"message too long: {len(v)} characters received, "
                f"maximum allowed is {settings.max_message_chars}."
            )
        return v

    @field_validator("history")
    @classmethod
    def history_capped(cls, v: list[dict]) -> list[dict]:
        # Keep at most 50 pairs (100 messages) to cap prompt size
        return v[-100:] if len(v) > 100 else v


async def _chat_stream(
    request: Request,
    session_id: str,
    message: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    """
    Stateless SSE pipe:
      1. Retrieve RAG context for the current message.
      2. Build prompt from frontend-supplied history (no server-side history lookup).
      3. Stream tokens straight to the client — no buffering, no post-stream writes.
      4. done / error events are guaranteed by llm_service to always close the stream.
    """
    app_state = request.app.state

    # RAG retrieval
    chunks = rag_service.retrieve(
        query=message,
        app_state=app_state,
        top_k=settings.top_k,
        threshold=settings.similarity_threshold,
    )
    enriched_chunks: list[dict] = []
    for chunk in chunks:
        doc = app_state.document_store.get(chunk.doc_id)
        enriched_chunks.append(
            {
                "filename": doc.filename if doc else chunk.doc_id,
                "chunk_index": 0,
                "text": chunk.text,
            }
        )

    # Build a lightweight in-request session from frontend history — never stored
    temp_session = Session(session_id=session_id)
    temp_session.messages = [
        Message(role=m["role"], content=m["content"])
        for m in history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    prompt_messages = session_service.build_prompt(
        session=temp_session,
        message=message,
        chunks=enriched_chunks,
        cfg=settings,
    )

    # Pure pipe — yield every SSE event directly, no buffering
    async for sse_event in llm_service.stream_completion(prompt_messages):
        yield sse_event


@router.post("/chat")
@limiter.limit("20/minute")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """
    POST /chat — validate session, then stream LLM response via SSE.

    Raises:
        HTTPException 404: session_id not found
    """
    try:
        session_service.get_session(request.app.state.session_store, body.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session_not_found")

    return StreamingResponse(
        _chat_stream(request, body.session_id, body.message, body.history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
