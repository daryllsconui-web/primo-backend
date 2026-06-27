"""
app/routers/session.py — Session lifecycle endpoints
  POST /session/new  → 201 { "session_id": "..." }
  GET  /session/{id} → 200 Session JSON | 404
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.models.session import Session
from app.services import session_service

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/new", status_code=status.HTTP_201_CREATED)
async def create_session(request: Request) -> dict[str, str]:
    """Create a new session and return its UUID v4 session_id."""
    session_store: dict = request.app.state.session_store
    session = session_service.create_session(session_store)
    return {"session_id": session.session_id}


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: str, request: Request) -> Session:
    """Return session data for the given session_id, or 404 if not found."""
    session_store: dict = request.app.state.session_store
    try:
        return session_service.get_session(session_store, session_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "session_not_found", "session_id": session_id},
        )
