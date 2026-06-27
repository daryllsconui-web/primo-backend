"""
app/models/config_models.py — AgentConfig and WidgetConfig Pydantic models
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class AgentConfig(BaseModel):
    name: str  # required; validated non-empty at startup
    personality: Optional[str] = None
    tone: Optional[str] = None
    system_prompt: Optional[str] = None  # max 2000 chars; validated at startup
    model: str = "llama3-8b-8192"  # validated against allowed model list


class WidgetConfig(BaseModel):
    backend_url: str  # required — no default
    primary_color: str = "#2563eb"
    background_color: str = "#ffffff"
    text_color: str = "#111827"
    agent_name: str = "Assistant"
    agent_avatar: Optional[str] = None  # URL; fallback: first letter of agentName
    welcome_message: str = "Hi! How can I help you?"
    position: Literal["bottom-right", "bottom-left", "top-right", "top-left"] = (
        "bottom-right"
    )
    font_family: str = "system-ui"
