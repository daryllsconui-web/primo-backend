"""
app/middleware/content_type.py — Enforce application/json on POST bodies
(stub; full impl in task 5)
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class ContentTypeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and not request.url.path.startswith("/ingest"):
            ct = request.headers.get("content-type", "")
            if "application/json" not in ct:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Expected Content-Type: application/json"},
                )
        return await call_next(request)
