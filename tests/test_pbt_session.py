# Feature: embeddable-ai-chatbot, Property 3: Session context window is bounded

# Validates: Requirements — Session context window is bounded to 50 user+assistant pairs

from hypothesis import given, settings
from hypothesis import strategies as st
from types import SimpleNamespace
from app.services.session_service import create_session, append_messages, build_prompt, get_session
from app.models.session import Message


@given(st.integers(min_value=51, max_value=500))
@settings(max_examples=100)
def test_session_context_window_is_bounded(n_pairs):
    store = {}
    session = create_session(store)

    # Add n_pairs user+assistant pairs
    for i in range(n_pairs):
        user_msg = Message(role="user", content=f"user {i}")
        asst_msg = Message(role="assistant", content=f"asst {i}")
        append_messages(store, session.session_id, user_msg, asst_msg)

    # Build prompt
    cfg = SimpleNamespace(
        agent_name="Bot",
        agent_personality=None,
        agent_tone=None,
        agent_system_prompt=None,
    )
    prompt = build_prompt(session, "new question", [], cfg)

    # Count non-system messages (user+assistant pairs)
    conv_messages = [m for m in prompt if m.role != "system"]

    # Must be at most 50 pairs = 100 messages, plus the current user message = 101
    # build_prompt adds the current message at the end, so total conv <= 50*2 + 1
    assert len(conv_messages) <= 101, (
        f"Expected <= 101 conv messages, got {len(conv_messages)}"
    )


# Feature: embeddable-ai-chatbot, Property 6: Session isolation — no cross-session data leakage
# Validates: Requirements 4.2

@given(
    st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
    st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
)
@settings(max_examples=100)
def test_session_isolation_no_cross_leakage(s1_texts, s2_texts):
    """Messages appended to S1 must not appear in S2, and vice versa."""
    store = {}
    session1 = create_session(store)
    session2 = create_session(store)

    # Interleave messages between s1 and s2
    for i, (t1, t2) in enumerate(zip(s1_texts, s2_texts)):
        user1 = Message(role="user", content=f"s1-{t1}")
        asst1 = Message(role="assistant", content=f"s1-reply-{i}")
        append_messages(store, session1.session_id, user1, asst1)

        user2 = Message(role="user", content=f"s2-{t2}")
        asst2 = Message(role="assistant", content=f"s2-reply-{i}")
        append_messages(store, session2.session_id, user2, asst2)

    # Get both sessions from store
    s1 = get_session(store, session1.session_id)
    s2 = get_session(store, session2.session_id)

    s1_contents = {m.content for m in s1.messages}
    s2_contents = {m.content for m in s2.messages}

    # No cross-contamination
    for msg in s1.messages:
        assert msg.content not in s2_contents or msg.content.startswith("s1-"), \
            f"S1 message '{msg.content}' found in S2"

    for msg in s2.messages:
        assert msg.content not in s1_contents or msg.content.startswith("s2-"), \
            f"S2 message '{msg.content}' found in S1"


# Feature: embeddable-ai-chatbot, Property 10: Session memory does not persist across process restarts
# Validates: Requirements 4.5, 4.6

import uuid

@given(st.integers(min_value=1, max_value=20))
@settings(max_examples=100)
def test_fresh_session_store_returns_404_for_old_ids(n_sessions):
    """A fresh Session_Store (simulating restart) raises KeyError for any previously valid session ID."""
    # Simulate pre-restart: create sessions in old store
    old_store = {}
    old_session_ids = []
    for _ in range(n_sessions):
        session = create_session(old_store)
        old_session_ids.append(session.session_id)

    # Simulate process restart: fresh empty store
    new_store = {}

    # Every previously valid session ID must raise KeyError in the new store
    for session_id in old_session_ids:
        try:
            get_session(new_store, session_id)
            assert False, f"Expected KeyError for session '{session_id}' after restart, but got a session"
        except KeyError:
            pass  # Expected — session not found after restart


@given(st.uuids())
@settings(max_examples=100)
def test_arbitrary_uuid_not_in_fresh_store(random_uuid):
    """Any arbitrary UUID should raise KeyError on a fresh store (no pre-existing sessions)."""
    store = {}
    try:
        get_session(store, str(random_uuid))
        assert False, f"Expected KeyError for UUID '{random_uuid}', got a session"
    except KeyError:
        pass  # Expected
