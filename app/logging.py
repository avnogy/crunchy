from __future__ import annotations

import logging
import re
import sys

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


_JELLYFIN_API_KEY_PATTERNS = (
    re.compile(r"(?i)(api_key=)[^&\s'\"]+"),
    re.compile(r"(?i)(x-emby-token:\s*)\S+"),
)


def redact_secrets(value: str, secrets: list[str] | None = None) -> str:
    """Remove known secrets and Jellyfin credential syntax from log text."""
    for pattern in _JELLYFIN_API_KEY_PATTERNS:
        value = pattern.sub(r"\1[REDACTED]", value)
    for secret in secrets or []:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


class RedactingFormatter(logging.Formatter):
    def __init__(self, *args: object, secrets: list[str] | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.secrets = secrets or []

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record), self.secrets)


def setup_logging(level: str = "INFO", secrets: list[str] | None = None) -> None:
    resolved_level = getattr(logging, str(level).upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    if not root_logger.handlers:
        root_handler = logging.StreamHandler(sys.stderr)
        root_logger.addHandler(root_handler)

    for handler in root_logger.handlers:
        handler.setLevel(resolved_level)
        handler.setFormatter(RedactingFormatter(LOG_FORMAT, secrets=secrets))

    for logger_name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.setLevel(resolved_level)
        uvicorn_logger.propagate = True
        uvicorn_logger.handlers.clear()
