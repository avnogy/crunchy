from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def setup_logging(level: str = "INFO") -> None:
    resolved_level = getattr(logging, str(level).upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    if not root_logger.handlers:
        root_handler = logging.StreamHandler(sys.stderr)
        root_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(root_handler)

    for handler in root_logger.handlers:
        handler.setLevel(resolved_level)

    for logger_name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.setLevel(resolved_level)
        uvicorn_logger.propagate = True
        uvicorn_logger.handlers.clear()
