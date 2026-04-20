from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.api_models import (
    SettingsModel,
)
from app.presets import get_effective_presets

logger = logging.getLogger(__name__)


class Settings(SettingsModel):
    model_config = {"extra": "forbid", "validate_assignment": True}


class EnvSettings(SettingsModel, BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        alias_generator=str.upper,
    )


def _get_settings_path() -> Path:
    return Path(os.getenv("SETTINGS_FILE", "/config/settings.json"))


def generate_app_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)[:length]


def _normalize_settings(settings: Settings) -> Settings:
    settings.presets = get_effective_presets(settings.presets)
    return settings


def _load_env_settings() -> Settings:
    env_settings = EnvSettings()
    return _normalize_settings(Settings.model_validate(env_settings.model_dump()))


def load_settings() -> Settings:
    path = _get_settings_path()

    if path.exists():
        try:
            raw_settings = json.loads(path.read_text())
            return _normalize_settings(Settings.model_validate(raw_settings))
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
