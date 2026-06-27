"""
app/routers/chat.py — POST /chat SSE streaming endpoint
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.models.session import Message
from app.services import llm_service, rag_service, session_service

# 20 messages per minute per IP — adjust as needed
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str

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


async def _chat_stream(
    request: Request,
    session_id: str,
    message: str,
) -> AsyncGenerator[str, None]:
    """
    Internal SSE generator.

    - Retrieves RAG context
    - Builds prompt via session_service
    - Streams tokens from llm_service
    - Buffers the full assistant reply
    - Appends user + assistant messages to session and trims to 50 after stream
    """
    app_state = request.app.state
    session = session_service.get_session(app_state.session_store, session_id)

    # RAG retrieval
    chunks = rag_service.retrieve(
        query=message,
        app_state=app_state,
        top_k=settings.top_k,
        threshold=settings.similarity_threshold,
    )
    chunks_as_dicts = [
        {
            "filename": c.doc_id,  # doc_id used as filename fallback if not stored
            "chunk_index": 0,
            "text": c.text,
        }
        for c in chunks
    ]

    # Enrich chunk dicts with actual filename from document_store when available
    enriched_chunks: list[dict] = []
    for chunk in chunks:
        doc = app_state.document_store.get(chunk.doc_id)
        filename = doc.filename if doc else chunk.doc_id
        enriched_chunks.append(
            {
                "filename": filename,
                "chunk_index": 0,
                "text": chunk.text,
            }
        )

    # Build full prompt (system + history + user message with optional RAG context)
    prompt_messages = session_service.build_prompt(
        session=session,
        message=message,
        chunks=enriched_chunks,
        cfg=settings,
    )

    # Stream tokens and buffer the complete assistant response
    assistant_tokens: list[str] = []
    stream_errored = False

    async for sse_event in llm_service.stream_completion(prompt_messages):
        yield sse_event

        # Parse to track buffered content and detect terminal events
        if sse_event.startswith("data: "):
            try:
                payload = json.loads(sse_event[6:].strip())
            except json.JSONDecodeError:
                continue

            if "token" in payload:
                assistant_tokens.append(payload["token"])
            elif "error" in payload:
                stream_errored = True
            # "done" is the other terminal case — loop exits naturally

    # Persist conversation only on clean completion
    if not stream_errored:
        assistant_content = "".join(assistant_tokens)
        user_msg = Message(role="user", content=message)
        assistant_msg = Message(role="assistant", content=assistant_content)

        session_service.append_messages(
            session_store=app_state.session_store,
            session_id=session_id,
            user_msg=user_msg,
            assistant_msg=assistant_msg,
        )
        session_service.trim_to_50(
            session_store=app_state.session_store,
            session_id=session_id,
        )


@router.post("/chat")
@limiter.limit("20/minute")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """
    POST /chat

    Validates session → runs RAG → streams Groq completion via SSE.

    Returns:
        StreamingResponse with media_type ``text/event-stream``

    Raises:
        HTTPException 404: session_id not found in session_store
    """
    try:
        session_service.get_session(request.app.state.session_store, body.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session_not_found")

    return StreamingResponse(
        _chat_stream(request, body.session_id, body.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
