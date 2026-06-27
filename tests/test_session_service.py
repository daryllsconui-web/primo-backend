"""
tests/test_session_service.py — Unit tests for session_service
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.session import Message, Session
from app.services import session_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store() -> dict:
    return {}


def _fake_settings(**kwargs: Any) -> SimpleNamespace:
    defaults = {
        "agent_name": "TestBot",
        "agent_personality": None,
        "agent_tone": None,
        "agent_system_prompt": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _user_msg(text: str) -> Message:
    return Message(role="user", content=text)


def _assistant_msg(text: str) -> Message:
    return Message(role="assistant", content=text)


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

def test_create_session_returns_session():
    store = _make_store()
    session = session_service.create_session(store)
    assert isinstance(session, Session)


def test_create_session_uuid_v4():
    store = _make_store()
    session = session_service.create_session(store)
    parsed = uuid.UUID(session.session_id, version=4)
    assert str(parsed) == session.session_id


def test_create_session_empty_messages():
    store = _make_store()
    session = session_service.create_session(store)
    assert session.messages == []


def test_create_session_stores_in_store():
    store = _make_store()
    session = session_service.create_session(store)
    assert session.session_id in store
    assert store[session.session_id] is session


def test_create_session_two_calls_different_ids():
    store = _make_store()
    s1 = session_service.create_session(store)
    s2 = session_service.create_session(store)
    assert s1.session_id != s2.session_id


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------

def test_get_session_returns_existing():
    store = _make_store()
    session = session_service.create_session(store)
    retrieved = session_service.get_session(store, session.session_id)
    assert retrieved is session


def test_get_session_raises_keyerror_for_missing():
    store = _make_store()
    with pytest.raises(KeyError):
        session_service.get_session(store, "nonexistent-id")


# ---------------------------------------------------------------------------
# append_messages
# ---------------------------------------------------------------------------

def test_append_messages_adds_both():
    store = _make_store()
    session = session_service.create_session(store)
    u = _user_msg("hello")
    a = _assistant_msg("hi")
    session_service.append_messages(store, session.session_id, u, a)
    assert session.messages == [u, a]


def test_append_messages_multiple_rounds():
    store = _make_store()
    session = session_service.create_session(store)
    for i in range(3):
        session_service.append_messages(
            store, session.session_id, _user_msg(f"u{i}"), _assistant_msg(f"a{i}")
        )
    assert len(session.messages) == 6


# ---------------------------------------------------------------------------
# trim_to_50
# ---------------------------------------------------------------------------

def test_trim_to_50_keeps_at_most_100_conv_messages():
    store = _make_store()
    session = session_service.create_session(store)
    # Add 60 pairs = 120 messages
    for i in range(60):
        session.messages.append(_user_msg(f"u{i}"))
        session.messages.append(_assistant_msg(f"a{i}"))
    session_service.trim_to_50(store, session.session_id)
    assert len(session.messages) == 100  # 50 pairs


def test_trim_to_50_preserves_system_messages():
    store = _make_store()
    session = session_service.create_session(store)
    system_msg = Message(role="system", content="You are TestBot.")
    session.messages.append(system_msg)
    for i in range(60):
        session.messages.append(_user_msg(f"u{i}"))
        session.messages.append(_assistant_msg(f"a{i}"))
    session_service.trim_to_50(store, session.session_id)
    # System message preserved + 100 conv messages
    assert session.messages[0].role == "system"
    assert len(session.messages) == 101


def test_trim_to_50_no_op_when_under_limit():
    store = _make_store()
    session = session_service.create_session(store)
    for i in range(10):
        session.messages.append(_user_msg(f"u{i}"))
        session.messages.append(_assistant_msg(f"a{i}"))
    session_service.trim_to_50(store, session.session_id)
    assert len(session.messages) == 20


def test_trim_to_50_retains_most_recent():
    store = _make_store()
    session = session_service.create_session(store)
    for i in range(60):
        session.messages.append(_user_msg(f"u{i}"))
        session.messages.append(_assistant_msg(f"a{i}"))
    session_service.trim_to_50(store, session.session_id)
    # Most recent pair should be u59/a59
    assert session.messages[-2].content == "u59"
    assert session.messages[-1].content == "a59"


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_first_message_is_system():
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings()
    result = session_service.build_prompt(session, "hello", [], cfg)
    assert result[0].role == "system"


def test_build_prompt_system_includes_agent_name():
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings(agent_name="Aria")
    result = session_service.build_prompt(session, "hello", [], cfg)
    assert "Aria" in result[0].content


def test_build_prompt_system_includes_personality_and_tone():
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings(agent_personality="cheerful", agent_tone="casual")
    result = session_service.build_prompt(session, "hello", [], cfg)
    system_content = result[0].content
    assert "cheerful" in system_content
    assert "casual" in system_content


def test_build_prompt_system_includes_system_prompt_text():
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings(agent_system_prompt="Always respond in bullet points.")
    result = session_service.build_prompt(session, "hello", [], cfg)
    assert "Always respond in bullet points." in result[0].content


def test_build_prompt_no_chunks_last_message_is_plain_user():
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings()
    result = session_service.build_prompt(session, "what time is it?", [], cfg)
    assert result[-1].role == "user"
    assert result[-1].content == "what time is it?"


def test_build_prompt_with_chunks_user_message_contains_context_block():
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings()
    chunks = [{"filename": "doc.txt", "chunk_index": 0, "text": "Some context."}]
    result = session_service.build_prompt(session, "summarise", chunks, cfg)
    last = result[-1]
    assert last.role == "user"
    assert "[CONTEXT]" in last.content
    assert "[/CONTEXT]" in last.content
    assert "Source: doc.txt, chunk 0" in last.content
    assert "Some context." in last.content
    assert "User: summarise" in last.content


def test_build_prompt_with_chunks_format_matches_spec():
    """Exact format: [CONTEXT]\\nSource: {f}, chunk {i}\\n{text}\\n---\\n[/CONTEXT]\\n\\nUser: {msg}"""
    store = _make_store()
    session = session_service.create_session(store)
    cfg = _fake_settings()
    chunks = [{"filename": "manual.pdf", "chunk_index": 2, "text": "Important info."}]
    result = session_service.build_prompt(session, "tell me", chunks, cfg)
    content = result[-1].content
    assert content.startswith("[CONTEXT]\n")
    assert "Source: manual.pdf, chunk 2\nImportant info.\n---\n[/CONTEXT]\n\nUser: tell me" in content


def test_build_prompt_includes_session_history():
    store = _make_store()
    session = session_service.create_session(store)
    session.messages.append(_user_msg("prior question"))
    session.messages.append(_assistant_msg("prior answer"))
    cfg = _fake_settings()
    result = session_service.build_prompt(session, "new question", [], cfg)
    # system + prior user + prior assistant + new user = 4
    assert len(result) == 4
    assert result[1].content == "prior question"
    assert result[2].content == "prior answer"
    assert result[3].content == "new question"


def test_build_prompt_excludes_system_messages_from_history():
    store = _make_store()
    session = session_service.create_session(store)
    session.messages.append(Message(role="system", content="Old system msg"))
    session.messages.append(_user_msg("q"))
    session.messages.append(_assistant_msg("a"))
    cfg = _fake_settings()
    result = session_service.build_prompt(session, "new", [], cfg)
    roles = [m.role for m in result]
    # Only one system message (freshly built), not the stale one from history
    assert roles.count("system") == 1
