from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any
from app.api_models import (
    SettingsValidationModel,
)

logger = logging.getLogger(__name__)
LEGACY_SETTINGS_KEYS = {"transcoding_temp_dir", "output_dir"}


class Settings(SettingsValidationModel):
    model_config = {"extra": "forbid", "validate_assignment": True}

    jellyfin_api_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    app_password: str = ""
    jobs_poll_interval_ms: int = Field(default=3000, ge=500)
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    presets: dict[str, Any] = Field(default_factory=dict)
    ffmpeg_flags: list[str] = Field(default_factory=list)
    redis_host: str = "redis"
    redis_port: int = Field(default=6379, ge=1, le=65535)


class EnvSettings(SettingsValidationModel, BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
    )

    jellyfin_api_url: str = Field(default="", alias="JELLYFIN_API_URL")
    jellyfin_api_key: str = Field(default="", alias="JELLYFIN_API_KEY")
    jellyfin_user_id: str = Field(default="", alias="JELLYFIN_USER_ID")
    app_password: str = Field(default="", alias="APP_PASSWORD")
    jobs_poll_interval_ms: int = Field(
        default=3000,
        ge=500,
        alias="JOBS_POLL_INTERVAL_MS",
    )
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, ge=1, le=65535, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    ffmpeg_flags: list[str] = Field(default_factory=list, alias="FFMPEG_FLAGS")
    redis_host: str = Field(default="redis", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, ge=1, le=65535, alias="REDIS_PORT")


def _get_settings_path() -> Path:
    return Path(os.getenv("SETTINGS_FILE", "/config/settings.json"))


def generate_app_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)[:length]


def _strip_legacy_settings_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in LEGACY_SETTINGS_KEYS}


def _load_env_settings() -> Settings:
    env_settings = EnvSettings()
    return Settings.model_validate(env_settings.model_dump())


def load_settings() -> Settings:
    path = _get_settings_path()

    if path.exists():
        try:
            raw_settings = json.loads(path.read_text())
            if isinstance(raw_settings, dict):
                raw_settings = _strip_legacy_settings_keys(raw_settings)
            settings = Settings.model_validate(raw_settings)
            if not settings.app_password:
                settings.app_password = _load_env_settings().app_password
            return settings
        except (json.JSONDecodeError, KeyError, ValidationError, ValueError) as e:
            logger.warning("Failed to load settings from %s: %s", path, e)

    return _load_env_settings()


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
