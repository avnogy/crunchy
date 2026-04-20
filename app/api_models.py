from __future__ import annotations

import shlex
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.logging import VALID_LOG_LEVELS


def normalize_jellyfin_url(value: Any) -> str:
    if isinstance(value, str):
        return value.rstrip("/")
    return str(value or "").rstrip("/")


def normalize_host(value: Any) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError("Host is required")
    return host


def normalize_log_level(value: Any) -> str:
    level = str(value or "INFO").upper()
    if level not in VALID_LOG_LEVELS:
        raise ValueError("Unsupported log level")
    return level


def parse_ffmpeg_flags(value: list[str] | str | None) -> list[str]:
    if isinstance(value, list):
        return [str(flag) for flag in value if str(flag).strip()]
    if isinstance(value, str):
        return shlex.split(value)
    return []


class SettingsPayload(BaseModel):
    model_config = {"extra": "forbid"}

    jellyfin_api_url: str | None = None
    jellyfin_api_key: str | None = None
    jellyfin_user_id: str | None = None
    app_password: str | None = None
    jobs_poll_interval_ms: int | None = Field(default=None, ge=500)
    app_host: str | None = None
    app_port: int | None = Field(default=None, ge=1, le=65535)
    log_level: str | None = None
    presets: dict[str, Any] | None = None
    ffmpeg_flags: list[str] | None = None
    redis_host: str | None = None
    redis_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("jellyfin_api_url", mode="before")
    @classmethod
    def validate_jellyfin_api_url(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_jellyfin_url(value)

    @field_validator("app_host", "redis_host", mode="before")
    @classmethod
    def validate_host(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_host(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_log_level(value)

    @field_validator("ffmpeg_flags", mode="before")
    @classmethod
    def validate_ffmpeg_flags(cls, value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        return parse_ffmpeg_flags(value)


class FfmpegPreviewPayload(BaseModel):
    model_config = {"extra": "forbid"}

    ffmpeg_flags: list[str] = Field(default_factory=list)

    @field_validator("ffmpeg_flags", mode="before")
    @classmethod
    def validate_ffmpeg_flags(cls, value: list[str] | str | None) -> list[str]:
        return parse_ffmpeg_flags(value)


class CreateJobPayload(BaseModel):
    model_config = {"extra": "forbid"}

    item_id: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    preset: str = Field(default="720p-low", min_length=1)
