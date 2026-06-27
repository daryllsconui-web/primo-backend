# Feature: embeddable-ai-chatbot, Property 7: SSE stream completeness
# Validates: Requirements 7.1, 7.3

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.llm_service import stream_completion


def _make_chunk(content):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return chunk


async def _collect(gen):
    events = []
    async for item in gen:
        events.append(item)
    return events


def _parse(events):
    payloads = []
    for e in events:
        if e.startswith("data: "):
            payloads.append(json.loads(e[6:].strip()))
    return payloads


def _patch_groq(chunks):
    async def _async_iter(_chunks):
        for c in _chunks:
            yield c

    async def async_create(*args, **kwargs):
        return _async_iter(chunks)

    mock_client = MagicMock()
    mock_client.chat.completions.create = async_create
    return patch("app.services.llm_service.groq.AsyncGroq", return_value=mock_client)


@given(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=50))
@settings(max_examples=100)
def test_successful_stream_has_tokens_and_done(tokens):
    """Mocked Groq returning N non-empty tokens → N token events + exactly 1 done event, 0 error events."""
    chunks = [_make_chunk(t) for t in tokens]
    messages = [{"role": "user", "content": "hi"}]

    with _patch_groq(chunks):
        events = asyncio.get_event_loop().run_until_complete(
            _collect(stream_completion(messages))
        )

    payloads = _parse(events)
    token_events = [p for p in payloads if "token" in p]
    done_events = [p for p in payloads if "done" in p]
    error_events = [p for p in payloads if "error" in p]

    assert len(token_events) == len(tokens), (
        f"Expected {len(tokens)} token events, got {len(token_events)}"
    )
    assert len(done_events) == 1, f"Expected exactly 1 done event, got {len(done_events)}"
    assert len(error_events) == 0, f"Expected 0 error events, got {len(error_events)}"


# Feature: embeddable-ai-chatbot, Property 8: Streaming error terminal event
# Validates: Requirements 7.4

@given(
    st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=20),
    st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_interrupted_stream_has_error_no_done(tokens, fail_at):
    """Groq raises exception at position fail_at → exactly 1 error event, 0 done events."""

    async def _raising_iter():
        for i, t in enumerate(tokens):
            if i >= fail_at:
                raise RuntimeError("Groq interrupted")
            yield _make_chunk(t)
        # If fail_at > len(tokens), raise after all tokens
        raise RuntimeError("Groq interrupted after tokens")

    async def async_create(*args, **kwargs):
        return _raising_iter()

    mock_client = MagicMock()
    mock_client.chat.completions.create = async_create

    messages = [{"role": "user", "content": "hi"}]

    with patch("app.services.llm_service.groq.AsyncGroq", return_value=mock_client):
        events = asyncio.get_event_loop().run_until_complete(
            _collect(stream_completion(messages))
        )

    payloads = _parse(events)
    error_events = [p for p in payloads if "error" in p]
    done_events = [p for p in payloads if "done" in p]

    assert len(error_events) == 1, f"Expected 1 error event, got {len(error_events)}"
    assert error_events[0]["error"] == "stream_interrupted"
    assert len(done_events) == 0, f"Expected 0 done events, got {len(done_events)}"
