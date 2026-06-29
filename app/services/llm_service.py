"""
app/services/llm_service.py — Groq async streaming client with multi-key rotation
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Union

import groq

from app.config import settings
from app.models.session import Message

logger = logging.getLogger(__name__)

BUSY_MESSAGE = (
    "Sai is a bit busy right now! "
    "Please resend your message in a few seconds."
)


async def stream_completion(
    messages: list[Union[Message, dict]],
) -> AsyncGenerator[str, None]:
    """
    Stream LLM completion from Groq with automatic key rotation on rate limit.

    Tries each available API key in order. If one is rate-limited (429),
    silently switches to the next key. If all keys are exhausted, yields
    a friendly retry message instead of a hard error.

    Yields SSE-formatted strings:
      - ``data: {"token": "..."}\\n\\n``  for each non-empty content chunk
      - ``data: {"done": true}\\n\\n``     on successful completion
      - ``data: {"error": "stream_interrupted"}\\n\\n``  on non-rate-limit errors
    """
    messages_dicts: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            messages_dicts.append({"role": m["role"], "content": m["content"]})
        else:
            messages_dicts.append({"role": m.role, "content": m.content})

    api_keys = settings.groq_api_keys
    last_attempt = len(api_keys) - 1

    for attempt, api_key in enumerate(api_keys):
        try:
            client = groq.AsyncGroq(api_key=api_key)
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
            return

        except groq.RateLimitError:
            if attempt < last_attempt:
                logger.warning("Groq key %d/%d rate limited — switching to next key.", attempt + 1, len(api_keys))
                continue
            # All keys exhausted — show friendly message as a normal Primo reply
            logger.warning("All %d Groq keys rate limited. Sending busy message.", len(api_keys))
            yield f"data: {json.dumps({'token': BUSY_MESSAGE})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            return

        except Exception as exc:
            logger.exception("Groq stream_completion failed.", extra={"error": str(exc)})
            yield f"data: {json.dumps({'error': 'stream_interrupted'})}\n\n"
            return
