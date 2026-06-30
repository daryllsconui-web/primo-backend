"""
app/services/llm_service.py — LLM streaming with provider switching.

LLM_PROVIDER=gemini  → Gemini 2.5 Flash (default)
LLM_PROVIDER=groq    → Groq with 4-key rotation (fallback / when Groq Developer tier available)
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Union

import groq
from google import genai
from google.genai import types as genai_types

from app.config import settings
from app.models.session import Message

logger = logging.getLogger(__name__)

BUSY_MESSAGE = (
    "Sai is a bit busy right now! "
    "Please resend your message in a few seconds."
)


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _stream_gemini(
    messages_dicts: list[dict],
) -> AsyncGenerator[str, None]:
    """Stream completion from Gemini 2.5 Flash via SSE."""
    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY is not set.")
        yield f"data: {json.dumps({'error': 'stream_interrupted'})}\n\n"
        return

    # Gemini separates system instruction from conversation contents
    system_instruction = None
    contents = []
    for m in messages_dicts:
        if m["role"] == "system":
            system_instruction = m["content"]
        else:
            # Gemini uses "model" instead of "assistant"
            role = "model" if m["role"] == "assistant" else "user"
            contents.append(
                genai_types.Content(
                    role=role,
                    parts=[genai_types.Part.from_text(text=m["content"])],
                )
            )

    config = genai_types.GenerateContentConfig(
        system_instruction=system_instruction,
    )

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        stream = await client.aio.models.generate_content_stream(
            model=settings.gemini_model,
            contents=contents,
            config=config,
        )
        async for chunk in stream:
            if chunk.text:
                yield f"data: {json.dumps({'token': chunk.text})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    except Exception as exc:
        # Google ClientError embeds the code in the string — check all known forms
        exc_str = str(exc)
        is_rate_limited = (
            "429" in exc_str
            or "RESOURCE_EXHAUSTED" in exc_str
            or getattr(exc, "status_code", None) == 429
            or getattr(getattr(exc, "status_code", None), "value", None) == 429
        )
        if is_rate_limited:
            logger.warning("Gemini rate limited.")
            yield f"data: {json.dumps({'token': BUSY_MESSAGE})}\n\n"
        else:
            logger.exception("Gemini stream_completion failed.")
            yield f"data: {json.dumps({'error': 'stream_interrupted'})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"


# ── Groq (backup — re-enable when Groq Developer tier is available) ───────────

async def _stream_groq(
    messages_dicts: list[dict],
) -> AsyncGenerator[str, None]:
    """
    Stream completion from Groq with automatic 4-key rotation on rate limit.
    Switch back by setting LLM_PROVIDER=groq in environment variables.
    """
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
            logger.warning("All %d Groq keys rate limited. Sending busy message.", len(api_keys))
            yield f"data: {json.dumps({'token': BUSY_MESSAGE})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            return

        except Exception as exc:
            logger.exception("Groq stream_completion failed.", extra={"error": str(exc)})
            yield f"data: {json.dumps({'error': 'stream_interrupted'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            return


# ── Public interface ──────────────────────────────────────────────────────────

async def stream_completion(
    messages: list[Union[Message, dict]],
) -> AsyncGenerator[str, None]:
    """
    Route to the active LLM provider based on LLM_PROVIDER env var.

    LLM_PROVIDER=gemini → Gemini 2.5 Flash
    LLM_PROVIDER=groq   → Groq with 4-key rotation
    """
    messages_dicts: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            messages_dicts.append({"role": m["role"], "content": m["content"]})
        else:
            messages_dicts.append({"role": m.role, "content": m.content})

    if settings.llm_provider == "groq":
        async for event in _stream_groq(messages_dicts):
            yield event
    else:
        async for event in _stream_gemini(messages_dicts):
            yield event
