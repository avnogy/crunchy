from __future__ import annotations

import json
import logging
import os
import secrets
import shlex
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from typing import Any

logger = logging.getLogger(__name__)


class Settings(BaseModel):
    model_config = {"extra": "forbid"}

    jellyfin_api_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    app_password: str = ""
    transcoding_temp_dir: Path = Path("/data/temp")
    output_dir: Path = Path("/data/output")
    jobs_poll_interval_ms: int = 3000
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    presets: dict[str, Any] = {}
    ffmpeg_flags: list[str] = []
    redis_host: str = "redis"
    redis_port: int = 6379

    @field_validator("jellyfin_api_url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        if isinstance(v, str):
            return v.rstrip("/")
        return v

    @field_validator("ffmpeg_flags", mode="before")
    @classmethod
    def parse_ffmpeg_flags(cls, v: list[str] | str | None) -> list[str]:
        if isinstance(v, list):
            return [str(flag) for flag in v if str(flag).strip()]
        if isinstance(v, str):
            return shlex.split(v)
        return []

    @field_validator("transcoding_temp_dir", "output_dir", mode="before")
    @classmethod
    def parse_path(cls, v: Path | str) -> Path:
        if isinstance(v, Path):
            return v
        return Path(v)


def _get_settings_path() -> Path:
    return Path(os.getenv("SETTINGS_FILE", "/config/settings.json"))


def generate_app_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)[:length]


def load_settings() -> Settings:
    path = _get_settings_path()

    if path.exists():
        try:
            settings = Settings.model_validate(json.loads(path.read_text()))
            if not settings.app_password:
                settings.app_password = os.getenv("APP_PASSWORD", "")
            return settings
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load settings from %s: %s", path, e)

    return Settings(
        jellyfin_api_url=os.getenv("JELLYFIN_API_URL", "").rstrip("/"),
        jellyfin_api_key=os.getenv("JELLYFIN_API_KEY", ""),
        jellyfin_user_id=os.getenv("JELLYFIN_USER_ID", ""),
        app_password=os.getenv("APP_PASSWORD", ""),
        transcoding_temp_dir=Path(os.getenv("TRANSCODING_TEMP_DIR", "/data/temp")),
        output_dir=Path(os.getenv("OUTPUT_DIR", "/data/output")),
        jobs_poll_interval_ms=int(os.getenv("JOBS_POLL_INTERVAL_MS", "3000")),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        redis_host=os.getenv("REDIS_HOST", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
    )


def save_settings(settings: Settings) -> None:
    path = _get_settings_path()
    data = settings.model_dump()
    data["app_password"] = settings.app_password
    serialized = json.dumps(data, indent=2)
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as tmp:
            tmp.write(serialized)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_path = Path(tmp.name)
        os.replace(temp_path, path)
    except Exception as e:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        logger.error("Failed to save settings to %s: %s", path, e)
        raise


def ensure_app_password(settings: Settings) -> None:
    if settings.app_password:
        if not _get_settings_path().exists():
            save_settings(settings)
        return

    settings.app_password = generate_app_password()
    logger.critical(
        "APP_PASSWORD was not set and no saved app password was found. Generated startup password for admin user: %s",
        settings.app_password,
    )
    save_settings(settings)
    logger.info("Persisted generated app password to %s", _get_settings_path())