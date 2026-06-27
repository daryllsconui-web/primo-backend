"""
app/logging_config.py — Structured JSON logging setup + secret redaction

Every log line is a single JSON object written to stdout:
  {"time": "...", "level": "INFO", "logger": "...", "message": "...", ...extra fields}

Secret redaction runs on every log record before emission — call configure_secrets()
once at startup so no registered secret value ever appears in log output.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Attributes that exist on every LogRecord — excluded from the extra-fields dump
_STANDARD_LOG_ATTRS: frozenset[str] = frozenset(
    {
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "id", "levelname", "levelno", "lineno", "message", "module", "msecs",
        "msg", "name", "pathname", "process", "processName", "relativeCreated",
        "stack_info", "thread", "threadName", "taskName",
    }
)

# --------------------------------------------------------------------------- #
# Secret registry — populated once at startup via configure_secrets()
# --------------------------------------------------------------------------- #
_secret_values: list[str] = []


def configure_secrets(secrets: list[str | None]) -> None:
    """
    Register secret values that must never appear in log output.

    Call once after settings are loaded:
        configure_secrets([settings.groq_api_key, settings.admin_api_key])

    None and empty-string values are ignored automatically.
    """
    global _secret_values
    _secret_values = [s for s in secrets if s]


def redact(text: str) -> str:
    """Replace every registered secret value in *text* with [REDACTED]."""
    for secret in _secret_values:
        text = text.replace(secret, "[REDACTED]")
    return text


# --------------------------------------------------------------------------- #
# Logging filter — scrubs secrets from every log record before emission
# --------------------------------------------------------------------------- #
class SecretRedactingFilter(logging.Filter):
    """
    Mutates each LogRecord in-place, replacing registered secret values with
    [REDACTED] in:
      - record.msg        (the message / format string)
      - record.args       (% formatting arguments — string args only)
      - extra dict fields (keys not in _STANDARD_LOG_ATTRS)

    Exception tracebacks (record.exc_info) are scrubbed inside _JsonFormatter
    where they are formatted into a string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not _secret_values:
            return True

        record.msg = redact(str(record.msg))

        if isinstance(record.args, dict):
            record.args = {
                k: redact(v) if isinstance(v, str) else v
                for k, v in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )

        # Scrub extra fields (e.g. method, path, traceback strings)
        for key in list(record.__dict__.keys()):
            if key not in _STANDARD_LOG_ATTRS:
                val = record.__dict__[key]
                if isinstance(val, str):
                    record.__dict__[key] = redact(val)

        return True


# --------------------------------------------------------------------------- #
# JSON formatter
# --------------------------------------------------------------------------- #
class _JsonFormatter(logging.Formatter):
    """Emits each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "time": (
                datetime.fromtimestamp(record.created, tz=timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach any extra fields passed via logger.info("msg", extra={...})
        for key, val in record.__dict__.items():
            if key not in _STANDARD_LOG_ATTRS:
                payload[key] = val

        if record.exc_info:
            # Scrub secrets from the formatted traceback before writing
            payload["traceback"] = redact(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Public setup function
# --------------------------------------------------------------------------- #
def setup_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with JSON output to stdout.

    Call once at application startup, then call configure_secrets() immediately
    after to register secrets for redaction.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(SecretRedactingFilter())

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party output — only warnings and above
    for noisy in ("sentence_transformers", "transformers", "torch", "faiss", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Uvicorn's built-in access log is replaced by our RequestLoggingMiddleware
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
