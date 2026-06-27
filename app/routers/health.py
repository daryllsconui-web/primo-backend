"""
app/routers/health.py — GET /health
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


def _get_memory_mb() -> float:
    """Read current process memory usage in MB (Linux /proc, fallback to 0)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024, 1)
    except Exception:
        pass
    return 0.0


@router.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    start_time: float = request.app.state.start_time
    uptime = int(time.time() - start_time)
    memory_mb = _get_memory_mb()
    return {
        "status": "ok",
        "uptime": uptime,
        "memory_mb": memory_mb,
        "memory_limit_mb": 512,
        "memory_used_pct": round((memory_mb / 512) * 100, 1) if memory_mb else None,
    }
