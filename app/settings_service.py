from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.api_models import SettingsPatch, SettingsView
from app.config import Settings, save_settings
from app.logging import VALID_LOG_LEVELS, setup_logging
from app.paths import OUTPUT_DIR, TRANSCODING_TEMP_DIR
from app.presets import NEW_PRESET_TEMPLATE, get_effective_presets

logger = logging.getLogger(__name__)

FFMPEG_RESERVED_FLAGS = {
    "-i",
    "-c",
    "-c:v",
    "-c:a",
    "-c:s",
    "-map",
    "-b:v",
    "-b:a",
    "-vf",
    "-hide_banner",
    "-loglevel",
    "-report",
    "-movflags",
    "-y",
    "-progress",
    "-stats_period",
}


def is_reserved_ffmpeg_flag(token: str) -> bool:
    """Return whether a flag overrides an option owned by the application."""
    option = token.split("=", 1)[0]
    return option in FFMPEG_RESERVED_FLAGS


def ensure_allowed_ffmpeg_flags(flags: list[str]) -> None:
    """Reject an entire flag set when it contains app-owned ffmpeg options."""
    rejected_flags = [flag for flag in flags if is_reserved_ffmpeg_flag(flag)]
    if rejected_flags:
        raise ValueError("FFmpeg flags contain reserved option(s): " + ", ".join(rejected_flags))


def validate_ffmpeg_flags(flags: list[str]) -> list[str]:
    try:
        ensure_allowed_ffmpeg_flags(flags)
    except ValueError as exc:
        logger.warning("Rejected ffmpeg flag configuration: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return flags


def build_settings_view(settings: Settings) -> SettingsView:
    payload = settings.model_dump(
        exclude={
            "jellyfin_api_key",
            "app_password",
        }
    )
    payload.update(
        jellyfin_api_key="",
        jellyfin_api_key_length=len(settings.jellyfin_api_key or ""),
        app_password="",
        app_password_length=len(settings.app_password or ""),
        transcoding_temp_dir=str(TRANSCODING_TEMP_DIR),
        output_dir=str(OUTPUT_DIR),
        new_preset_template=NEW_PRESET_TEMPLATE,
        valid_log_levels=list(VALID_LOG_LEVELS),
    )
    return SettingsView(**payload)


def update_settings(app_state: Any, payload: SettingsPatch) -> Settings:
    current = app_state.settings
    updated_settings = current.model_copy()
    previous_log_level = current.log_level

    updates = payload.model_dump(exclude_none=True)
    secret_keys = {"jellyfin_api_key", "app_password"}

    for field, value in updates.items():
        if field in secret_keys:
            if value:
                setattr(updated_settings, field, value)
            continue
        if field == "presets":
            updated_settings.presets = get_effective_presets(value)
            continue
        if field == "ffmpeg_flags":
            updated_settings.ffmpeg_flags = validate_ffmpeg_flags(value)
            continue
        setattr(updated_settings, field, value)

    updated_settings.presets = get_effective_presets(updated_settings.presets)
    save_settings(updated_settings)
    app_state.settings = updated_settings

    setup_logging(
        updated_settings.log_level,
        [updated_settings.jellyfin_api_key, updated_settings.app_password],
    )
    if updated_settings.log_level != previous_log_level:
        logger.info("Log level updated to %s", updated_settings.log_level)
        logger.debug("Debug logging is now enabled")
        logger.warning("Warning logging remains enabled")

    logger.info(
        "Settings saved app=%s:%s redis=%s:%s poll_interval_ms=%s",
        updated_settings.app_host,
        updated_settings.app_port,
        updated_settings.redis_host,
        updated_settings.redis_port,
        updated_settings.jobs_poll_interval_ms,
    )
    return updated_settings
