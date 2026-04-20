from __future__ import annotations

import logging
import shutil
from pathlib import Path

import redis
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api_models import FfmpegPreviewPayload, SettingsPayload
from app.config import Settings, save_settings
from app.jobs import get_redis_client
from app.logging import VALID_LOG_LEVELS, setup_logging
from app.paths import OUTPUT_DIR, TRANSCODING_TEMP_DIR
from app.presets import NEW_PRESET_TEMPLATE, get_effective_presets
from app.transcode import get_ffmpeg_command

logger = logging.getLogger(__name__)

router = APIRouter()

FFMPEG_RESERVED_FLAGS = {
    "-i",
    "-c",
    "-c:v",
    "-c:a",
    "-b:v",
    "-b:a",
    "-vf",
    "-hide_banner",
    "-loglevel",
    "-movflags",
    "-y",
    "-progress",
    "-stats_period",
}

def build_settings_response(settings: Settings, presets: dict) -> dict:
    data = settings.model_dump()
    data["transcoding_temp_dir"] = str(TRANSCODING_TEMP_DIR)
    data["output_dir"] = str(OUTPUT_DIR)
    data["jellyfin_api_key"] = ""
    data["jellyfin_api_key_length"] = len(settings.jellyfin_api_key or "")
    data["app_password"] = ""
    data["app_password_length"] = len(settings.app_password or "")
    data["presets"] = presets
    data["new_preset_template"] = NEW_PRESET_TEMPLATE
    data["valid_log_levels"] = list(VALID_LOG_LEVELS)
    return data


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


def validate_ffmpeg_flags(flags: list[str]) -> list[str]:
    for token in flags:
        if token in FFMPEG_RESERVED_FLAGS:
            logger.warning("Rejected reserved ffmpeg flag: %s", token)
            raise HTTPException(
                status_code=400,
                detail=f"Flag '{token}' is not allowed as it conflicts with required options",
            )

    return flags


@router.get("/api/settings")
async def get_settings(request: Request):
    settings = request.app.state.settings
    logger.debug("Returning settings payload")
    data = build_settings_response(settings, request.app.state.presets)
    return JSONResponse({"settings": data})


@router.get("/api/ffmpeg-command")
async def get_ffmpeg_command_api(request: Request):
    settings = request.app.state.settings
    logger.debug("Generating ffmpeg command preview from saved settings")
    cmd = get_ffmpeg_command(settings)
    return JSONResponse({"command": cmd})


@router.post("/api/ffmpeg-preview")
async def ffmpeg_preview(request: Request, payload: FfmpegPreviewPayload):
    flags = validate_ffmpeg_flags(payload.ffmpeg_flags)
    logger.debug("Building ffmpeg preview with %d custom flag token(s)", len(flags))
    cmd = get_ffmpeg_command(Settings(ffmpeg_flags=flags))
    logger.debug("Returning ffmpeg preview command with %d argument(s)", len(cmd))
    return JSONResponse({"command": cmd})


@router.post("/api/settings")
async def update_settings(request: Request, data: SettingsPayload):
    settings = request.app.state.settings
    updated_settings = settings.model_copy()
    logger.info("Updating settings")

    if data.jellyfin_api_url is not None:
        updated_settings.jellyfin_api_url = data.jellyfin_api_url
    if data.jellyfin_user_id is not None:
        updated_settings.jellyfin_user_id = data.jellyfin_user_id
    if data.app_host is not None:
        updated_settings.app_host = data.app_host
    if data.app_port is not None:
        updated_settings.app_port = data.app_port
    if data.redis_host is not None:
        updated_settings.redis_host = data.redis_host
    if data.redis_port is not None:
        updated_settings.redis_port = data.redis_port
    if data.jobs_poll_interval_ms is not None:
        updated_settings.jobs_poll_interval_ms = data.jobs_poll_interval_ms
    if data.log_level is not None:
        updated_settings.log_level = data.log_level
    if data.presets is not None:
        updated_settings.presets = get_effective_presets(data.presets)
    if data.ffmpeg_flags is not None:
        updated_settings.ffmpeg_flags = validate_ffmpeg_flags(data.ffmpeg_flags)

    if data.jellyfin_api_key:
        updated_settings.jellyfin_api_key = data.jellyfin_api_key
    if data.app_password:
        updated_settings.app_password = data.app_password

    save_settings(updated_settings)
    request.app.state.settings = updated_settings
    request.app.state.presets = updated_settings.presets
    if data.log_level:
        setup_logging(updated_settings.log_level)
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
    response_settings = build_settings_response(
        updated_settings, request.app.state.presets
    )
    return JSONResponse({"settings": response_settings})


@router.post("/api/settings/clear-temp")
async def clear_temp_directory(request: Request):
    logger.warning("Clearing worker temp directory %s", TRANSCODING_TEMP_DIR)
    removed = clear_directory_contents(TRANSCODING_TEMP_DIR)
    logger.info(
        "Cleared worker temp directory %s removed=%d",
        TRANSCODING_TEMP_DIR,
        removed,
    )
    return JSONResponse({"cleared": removed, "path": str(TRANSCODING_TEMP_DIR)})


@router.post("/api/settings/clear-output")
async def clear_output_directory(request: Request):
    logger.warning("Clearing output directory %s", OUTPUT_DIR)
    removed = clear_directory_contents(OUTPUT_DIR)
    logger.info("Cleared output directory %s removed=%d", OUTPUT_DIR, removed)
    return JSONResponse({"cleared": removed, "path": str(OUTPUT_DIR)})


@router.get("/api/redis-health")
async def redis_health(request: Request):
    settings = request.app.state.settings
    try:
        client = get_redis_client(settings)
        client.ping()
    except redis.RedisError as exc:
        logger.warning("Redis health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    return JSONResponse({"status": "ok"})


@router.get("/settings")
async def settings_page(request: Request):
    templates = request.app.state.templates
    logger.debug("Rendering settings page")
    return templates.TemplateResponse(
        "settings/index.html",
        {
            "request": request,
            "active_page": "settings",
            "valid_log_levels": VALID_LOG_LEVELS,
            "transcoding_temp_dir": str(TRANSCODING_TEMP_DIR),
            "output_dir": str(OUTPUT_DIR),
        },
    )
