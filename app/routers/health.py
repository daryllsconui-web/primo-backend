"""
app/routers/health.py — GET /health
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    start_time: float = request.app.state.start_time
    uptime = int(time.time() - start_time)
    return {"status": "ok", "uptime": uptime}
