from __future__ import annotations

from pathlib import Path

TRANSCODING_TEMP_DIR = Path("/data/temp")
OUTPUT_DIR = Path("/data/output")
MANAGED_DIRECTORIES = (TRANSCODING_TEMP_DIR, OUTPUT_DIR)


def ensure_managed_directories() -> None:
    for directory in MANAGED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
