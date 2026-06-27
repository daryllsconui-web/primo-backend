"""
app/middleware/exception_handler.py — Catch-all 500 handler

Tracebacks are scrubbed of secrets by SecretRedactingFilter (via the logging
pipeline) and by the _JsonFormatter (for exc_info text), so no manual
redaction is needed here.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log sanitised stack trace (secrets auto-redacted); return generic 500 body."""
    logger.error(
        "Unhandled exception.",
        exc_info=exc,
        extra={
            "method": request.method,
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=500,
        content={"error": "An internal server error occurred"},
    )
