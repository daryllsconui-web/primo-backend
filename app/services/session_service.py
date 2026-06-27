"""
app/services/session_service.py — Session management: CRUD + context window
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.models.session import Message, Session

logger = logging.getLogger(__name__)


def create_session(session_store: dict[str, Session]) -> Session:
    """Create a new session with UUID v4 ID and empty message list."""
    session_id = str(uuid.uuid4())
    session = Session(session_id=session_id)
    session_store[session_id] = session
    return session


def get_session(session_store: dict[str, Session], session_id: str) -> Session:
    """
    Retrieve session by ID and refresh its last_active_at timestamp.
    Raises KeyError (→ 404) if not found.
    """
    if session_id not in session_store:
        raise KeyError(f"Session '{session_id}' not found.")
    session = session_store[session_id]
    session.last_active_at = datetime.now(timezone.utc)
    return session


def append_messages(
    session_store: dict[str, Session],
    session_id: str,
    user_msg: Message,
    assistant_msg: Message,
) -> None:
    """Append a user message and an assistant message to the session history."""
    session = get_session(session_store, session_id)
    session.messages.append(user_msg)
    session.messages.append(assistant_msg)


def cleanup_expired_sessions(
    session_store: dict[str, Session],
    ttl_minutes: int,
) -> int:
    """
    Delete sessions that have been inactive for longer than ttl_minutes.
    Returns the number of sessions removed.
    """
    now = datetime.now(timezone.utc)
    expired = [
        sid
        for sid, session in session_store.items()
        if (now - session.last_active_at.replace(tzinfo=timezone.utc)).total_seconds()
        > ttl_minutes * 60
    ]
    for sid in expired:
        del session_store[sid]

    if expired:
        logger.info("Session cleanup: removed %d expired session(s).", len(expired))

    return len(expired)


def trim_to_50(session_store: dict[str, Session], session_id: str) -> None:
    """
    Retain the 50 most recent user+assistant pairs.
    System messages at index 0 are always preserved.
    """
    session = get_session(session_store, session_id)
    messages = session.messages

    # Separate system messages from conversational messages
    system_messages = [m for m in messages if m.role == "system"]
    conv_messages = [m for m in messages if m.role != "system"]

    # Keep at most 50 pairs = 100 conversational messages
    max_conv = 50 * 2  # 50 user + 50 assistant
    if len(conv_messages) > max_conv:
        conv_messages = conv_messages[-max_conv:]

    session.messages = system_messages + conv_messages


def build_prompt(
    session: Session,
    message: str,
    chunks: list[dict[str, Any]],
    cfg: Any = None,
) -> list[Message]:
    """
    Build the full prompt list for the LLM.

    Order:
      1. System message (agent identity + personality/tone + system_prompt)
      2. Session history (last 50 pairs, non-system messages)
      3. Current user message — with RAG context injected if chunks are present

    The RAG context format (when chunks provided):
      [CONTEXT]
      Source: {filename}, chunk {index}
      {chunk_text}
      ---
      [/CONTEXT]

      User: {message}

    Args:
        session:  Active Session object.
        message:  The current user message text.
        chunks:   List of RAG chunk dicts with keys: filename, chunk_index, text.
        cfg:      Settings object (defaults to module-level ``settings`` singleton).
    """
    effective_settings = cfg if cfg is not None else settings

    prompt: list[Message] = []

    # 1. Build system prompt from settings
    system_parts: list[str] = []

    name = getattr(effective_settings, "agent_name", None)
    personality = getattr(effective_settings, "agent_personality", None)
    tone = getattr(effective_settings, "agent_tone", None)
    system_prompt_text = getattr(effective_settings, "agent_system_prompt", None)

    if name:
        system_parts.append(f"You are {name}.")

    if personality:
        system_parts.append(f"Personality: {personality}.")

    if tone:
        system_parts.append(f"Tone: {tone}.")

    if system_prompt_text:
        system_parts.append(system_prompt_text)

    system_content = " ".join(system_parts) if system_parts else f"You are {name or 'Assistant'}."
    prompt.append(Message(role="system", content=system_content))

    # 2. Append session history (non-system messages only; capped to last 50 pairs = 100 messages)
    conv_history = [m for m in session.messages if m.role != "system"]
    conv_history = conv_history[-100:]  # enforce 50-pair window
    for m in conv_history:
        prompt.append(m)

    # 3. Build current user message — inject RAG context block if chunks are present
    if chunks:
        context_lines: list[str] = ["[CONTEXT]"]
        for chunk in chunks:
            text = chunk.get("text", "")
            context_lines.append(text)
            context_lines.append("---")
        context_lines.append("[/CONTEXT]")
        context_block = "\n".join(context_lines)
        user_content = f"{context_block}\n\nUser: {message}"
    else:
        user_content = message

    prompt.append(Message(role="user", content=user_content))

    return prompt
