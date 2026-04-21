from __future__ import annotations

import shutil
from pathlib import Path

TRANSCODING_TEMP_DIR = Path("/data/temp")
OUTPUT_DIR = Path("/data/output")
MANAGED_DIRECTORIES = (TRANSCODING_TEMP_DIR, OUTPUT_DIR)


def ensure_managed_directories() -> None:
    for directory in MANAGED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


def clear_directory_contents(directory: Path) -> int:
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return 0

    removed = 0
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    return removed
