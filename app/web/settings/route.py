from __future__ import annotations

import logging

import redis.asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api_models import FfmpegPreviewPayload, SettingsPatch
from app.jobs import get_redis_client
from app.logging import VALID_LOG_LEVELS
from app.paths import (
    OUTPUT_DIR,
    TRANSCODING_TEMP_DIR,
    clear_directory_contents,
)
from app.settings_service import (
    build_settings_view,
    update_settings,
    validate_ffmpeg_flags,
)
from app.transcode import get_ffmpeg_command

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/settings")
async def get_settings(request: Request):
    settings = request.app.state.settings
    logger.debug("Returning settings payload")
    data = build_settings_view(settings)
    return JSONResponse({"settings": data.model_dump()})


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
    preview_settings = request.app.state.settings.model_copy(
        update={"ffmpeg_flags": flags}
    )
    cmd = get_ffmpeg_command(
        preview_settings,
    )
    logger.debug("Returning ffmpeg preview command with %d argument(s)", len(cmd))
    return JSONResponse({"command": cmd})


@router.post("/api/settings")
async def update_settings_route(request: Request, data: SettingsPatch):
    logger.info("Updating settings")
    updated_settings = update_settings(request.app.state, data)
    response_settings = build_settings_view(updated_settings)
    return JSONResponse({"settings": response_settings.model_dump()})


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
        await client.ping()
    except redis.asyncio.RedisError as exc:
        logger.warning("Redis health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    return JSONResponse({"status": "ok"})


@router.get("/settings")
async def settings_page(request: Request):
    templates = request.app.state.templates
    logger.debug("Rendering settings page")
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {
            "active_page": "settings",
            "valid_log_levels": VALID_LOG_LEVELS,
            "transcoding_temp_dir": str(TRANSCODING_TEMP_DIR),
            "output_dir": str(OUTPUT_DIR),
        },
    )
