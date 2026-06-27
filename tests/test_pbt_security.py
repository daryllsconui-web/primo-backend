# Feature: embeddable-ai-chatbot, Property 9: API key never in response body
# Validates: Requirements 8.3

import json
import asyncio
from unittest.mock import MagicMock, patch
from hypothesis import given, settings
from hypothesis import strategies as st

# Use a clearly fake API key for testing — never use a real key
FAKE_API_KEY = "gsk_TestFakeKeyForPBTOnly_DoNotUse_1234567890abcdef"


@given(st.text(min_size=0, max_size=200))
@settings(max_examples=100, deadline=None)
def test_exception_handler_response_never_contains_api_key(exception_message):
    """500 response body must never contain any substring of the GROQ_API_KEY."""
    from fastapi import Request
    from app.middleware.exception_handler import unhandled_exception_handler

    # Patch settings.groq_api_key with our fake key
    with patch("app.middleware.exception_handler.settings") as mock_settings:
        mock_settings.groq_api_key = FAKE_API_KEY

        # Create a mock request
        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/chat"

        # Create exception that embeds the API key in its message
        exc = RuntimeError(f"Connection failed with key {FAKE_API_KEY}: {exception_message}")

        response = asyncio.run(unhandled_exception_handler(mock_request, exc))

        body = response.body.decode("utf-8")

        # The response body must not contain the API key or any significant substring
        assert FAKE_API_KEY not in body, f"API key found in response body: {body}"
        # Also check substrings of the key (at least 8 chars)
        for i in range(len(FAKE_API_KEY) - 7):
            substring = FAKE_API_KEY[i:i+8]
            assert substring not in body, f"API key substring '{substring}' found in response body"


@given(st.text(min_size=0, max_size=200))
@settings(max_examples=100, deadline=None)
def test_500_response_body_is_generic(exception_message):
    """500 response body is always the generic error message, never exception details."""
    from fastapi import Request
    from app.middleware.exception_handler import unhandled_exception_handler

    with patch("app.middleware.exception_handler.settings") as mock_settings:
        mock_settings.groq_api_key = FAKE_API_KEY

        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/health"

        exc = ValueError(exception_message)

        response = asyncio.run(unhandled_exception_handler(mock_request, exc))

        assert response.status_code == 500
        body = json.loads(response.body.decode("utf-8"))
        assert "error" in body
        assert body["error"] == "An internal server error occurred"
        # Exception details must not appear
        if exception_message:
            assert exception_message not in response.body.decode("utf-8") or len(exception_message) < 3
