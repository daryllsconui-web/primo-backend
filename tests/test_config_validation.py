"""
tests/test_config_validation.py — Unit tests for Settings validation (app/config.py)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


# ---------------------------------------------------------------------------
# Helpers — minimal valid kwargs so validators don't cascade
# ---------------------------------------------------------------------------

def _valid_kwargs(**overrides) -> dict:
    """Base valid settings; override specific fields per test."""
    base = {
        "groq_api_key": "test-key",
        "agent_name": "TestBot",
        "groq_model": "llama3-8b-8192",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# agent_name validation
# ---------------------------------------------------------------------------

def test_agent_name_empty_raises_validation_error():
    """AGENT_NAME == '' must raise ValidationError at startup."""
    with pytest.raises(ValidationError):
        Settings(**_valid_kwargs(agent_name=""))


def test_agent_name_whitespace_only_raises_validation_error():
    """AGENT_NAME == '   ' (whitespace-only) must raise ValidationError."""
    with pytest.raises(ValidationError):
        Settings(**_valid_kwargs(agent_name="   "))


def test_agent_name_valid_loads_fine():
    """Valid AGENT_NAME with no AGENT_SYSTEM_PROMPT → Settings loads without error."""
    s = Settings(**_valid_kwargs(agent_name="Aria"))
    assert s.agent_name == "Aria"
    assert s.agent_system_prompt is None


# ---------------------------------------------------------------------------
# agent_system_prompt validation
# ---------------------------------------------------------------------------

def test_agent_system_prompt_over_2000_chars_raises_validation_error():
    """AGENT_SYSTEM_PROMPT > 2000 chars must raise ValidationError."""
    long_prompt = "x" * 2001
    with pytest.raises(ValidationError):
        Settings(**_valid_kwargs(agent_system_prompt=long_prompt))


def test_agent_system_prompt_exactly_2000_chars_is_valid():
    """AGENT_SYSTEM_PROMPT == 2000 chars (boundary) must load fine."""
    prompt_2000 = "y" * 2000
    s = Settings(**_valid_kwargs(agent_system_prompt=prompt_2000))
    assert len(s.agent_system_prompt) == 2000


def test_agent_system_prompt_absent_loads_fine():
    """No AGENT_SYSTEM_PROMPT → Settings loads; field defaults to None."""
    s = Settings(**_valid_kwargs())
    assert s.agent_system_prompt is None


# ---------------------------------------------------------------------------
# groq_model validation
# ---------------------------------------------------------------------------

def test_groq_model_invalid_value_raises_validation_error():
    """GROQ_MODEL with unsupported value must raise ValidationError."""
    with pytest.raises(ValidationError):
        Settings(**_valid_kwargs(groq_model="gpt-4o"))


def test_groq_model_valid_value_loads_fine():
    """Recognised GROQ_MODEL value must load without error."""
    s = Settings(**_valid_kwargs(groq_model="llama3-70b-8192"))
    assert s.groq_model == "llama3-70b-8192"


def test_groq_model_default_is_valid():
    """Default GROQ_MODEL ('llama3-8b-8192') must be accepted."""
    s = Settings(**_valid_kwargs())
    assert s.groq_model == "llama3-8b-8192"
