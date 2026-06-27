"""
tests/test_llm_service.py — Unit tests for app/services/llm_service.py
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_service import stream_completion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(content: str | None) -> MagicMock:
    """Build a fake Groq stream chunk."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return chunk


async def _collect(gen) -> list[str]:
    """Drain an async generator into a list."""
    events: list[str] = []
    async for item in gen:
        events.append(item)
    return events


def _parse_events(events: list[str]) -> list[dict]:
    """Parse raw SSE strings into payload dicts."""
    payloads: list[dict] = []
    for event in events:
        assert event.startswith("data: "), f"Unexpected event format: {event!r}"
        payloads.append(json.loads(event[6:].strip()))
    return payloads


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------

def _patch_groq(chunks: list[MagicMock]):
    """
    Return a context-manager patch that makes AsyncGroq().chat.completions.create
    return an async iterable of *chunks*.
    """

    async def _async_iter(_chunks):
        for c in _chunks:
            yield c

    mock_stream = _async_iter(chunks)

    mock_create = AsyncMock(return_value=mock_stream)
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    return patch("app.services.llm_service.groq.AsyncGroq", return_value=mock_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_three_tokens_emitted():
    """Mock Groq returning 3 non-empty tokens → 3 token events + 1 done event."""
    chunks = [
        _make_chunk("Hello"),
        _make_chunk(" world"),
        _make_chunk("!"),
    ]

    messages = [{"role": "user", "content": "hi"}]

    with _patch_groq(chunks):
        events = await _collect(stream_completion(messages))

    payloads = _parse_events(events)

    token_payloads = [p for p in payloads if "token" in p]
    done_payloads = [p for p in payloads if "done" in p]
    error_payloads = [p for p in payloads if "error" in p]

    assert len(token_payloads) == 3
    assert [p["token"] for p in token_payloads] == ["Hello", " world", "!"]
    assert len(done_payloads) == 1
    assert done_payloads[0]["done"] is True
    assert len(error_payloads) == 0


@pytest.mark.asyncio
async def test_empty_tokens_only_done_emitted():
    """Mock Groq returning None/empty content → only done event, no token events."""
    chunks = [
        _make_chunk(None),
        _make_chunk(""),
        _make_chunk(None),
    ]

    messages = [{"role": "user", "content": "hi"}]

    with _patch_groq(chunks):
        events = await _collect(stream_completion(messages))

    payloads = _parse_events(events)

    token_payloads = [p for p in payloads if "token" in p]
    done_payloads = [p for p in payloads if "done" in p]
    error_payloads = [p for p in payloads if "error" in p]

    assert len(token_payloads) == 0
    assert len(done_payloads) == 1
    assert len(error_payloads) == 0


@pytest.mark.asyncio
async def test_exception_yields_error_no_done():
    """Mock Groq raising an exception → exactly 1 error event, no done event."""

    async def _raising_create(*args, **kwargs):
        raise RuntimeError("Groq connection failed")

    mock_client = MagicMock()
    mock_client.chat.completions.create = _raising_create

    messages = [{"role": "user", "content": "hi"}]

    with patch("app.services.llm_service.groq.AsyncGroq", return_value=mock_client):
        events = await _collect(stream_completion(messages))

    payloads = _parse_events(events)

    error_payloads = [p for p in payloads if "error" in p]
    done_payloads = [p for p in payloads if "done" in p]
    token_payloads = [p for p in payloads if "token" in p]

    assert len(error_payloads) == 1
    assert error_payloads[0]["error"] == "stream_interrupted"
    assert len(done_payloads) == 0
    assert len(token_payloads) == 0


@pytest.mark.asyncio
async def test_system_prompt_in_messages_passed_to_groq():
    """Verify the system prompt content is included in messages sent to Groq."""
    chunks = [_make_chunk("ok")]

    system_content = "You are TestBot. Personality: cheerful. Tone: casual."
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "hello"},
    ]

    mock_create = AsyncMock()

    async def _async_iter(_):
        for c in chunks:
            yield c

    mock_create.return_value = _async_iter(None)

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("app.services.llm_service.groq.AsyncGroq", return_value=mock_client):
        events = await _collect(stream_completion(messages))

    # Confirm create was called once
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args

    # Extract messages argument (positional or keyword)
    passed_messages = call_kwargs.kwargs.get("messages") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    )
    assert passed_messages is not None, "messages not passed to Groq create()"

    # System message should be first and contain the expected content
    system_msgs = [m for m in passed_messages if m["role"] == "system"]
    assert len(system_msgs) >= 1
    assert system_content in system_msgs[0]["content"]

    # Stream should complete normally
    payloads = _parse_events(events)
    done_payloads = [p for p in payloads if "done" in p]
    assert len(done_payloads) == 1
