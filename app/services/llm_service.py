"""
app/services/llm_service.py — Groq async streaming client wrapper
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Union

import groq

from app.config import settings
from app.models.session import Message

logger = logging.getLogger(__name__)


async def stream_completion(
    messages: list[Union[Message, dict]],
) -> AsyncGenerator[str, None]:
    """
    Stream LLM completion from Groq.

    Yields SSE-formatted strings:
      - ``data: {"token": "..."}\\n\\n``  for each non-empty content chunk
      - ``data: {"done": true}\\n\\n``     on successful completion
      - ``data: {"error": "stream_interrupted"}\\n\\n``  on any exception (terminal)

    Args:
        messages: List of Message pydantic objects or plain dicts with
                  ``role`` and ``content`` keys.
    """
    # Normalise to plain dicts for the Groq SDK
    messages_dicts: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            messages_dicts.append({"role": m["role"], "content": m["content"]})
        else:
            messages_dicts.append({"role": m.role, "content": m.content})

    try:
        client = groq.AsyncGroq(api_key=settings.groq_api_key)
        stream = await client.chat.completions.create(
            model=settings.groq_model,
            messages=messages_dicts,  # type: ignore[arg-type]
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield f"data: {json.dumps({'token': content})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"

    except Exception as exc:
        logger.exception("Groq stream_completion failed.", extra={"error": str(exc)})
        yield f"data: {json.dumps({'error': 'stream_interrupted'})}\n\n"
